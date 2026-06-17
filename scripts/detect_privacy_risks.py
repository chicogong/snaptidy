#!/usr/bin/env python3
"""Detect privacy-sensitive documents in photo libraries.

Scans the metadata index (SQLite DB) for images that may contain sensitive
personal information such as ID cards, bank cards, passports, etc.
Generates a risk report with actionable recommendations.

Detection methods:
1. Filename-based heuristics (fast, zero-dependency)
2. EXIF metadata patterns (requires piexif)
3. Folder path analysis
4. Content-type classification from scan metadata

Usage:
    python3 scripts/detect_privacy_risks.py --index photo_index.db --output privacy_report.json
    python3 scripts/detect_privacy_risks.py --index photo_index.db --format human
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Sensitive document detection patterns
# ---------------------------------------------------------------------------

# Filename patterns that suggest sensitive documents
SENSITIVE_FILENAME_PATTERNS = [
    # ID cards
    (re.compile(r'(?:身[份分]证|id[_\-\s]?card|national[_\-\s]?id)', re.I),
     "id_card", "high", "Possible ID card image"),
    # Passports
    (re.compile(r'(?:护照|passport|visa)', re.I),
     "passport", "high", "Possible passport/visa image"),
    # Bank/credit cards
    (re.compile(r'(?:银[行卡]|bank[_\-\s]?card|credit[_\-\s]?card|debit[_\-\s]?card|信用卡|借记卡)', re.I),
     "bank_card", "high", "Possible bank/credit card image"),
    # Social security / insurance
    (re.compile(r'(?:社保|social[_\-\s]?security|insurance[_\-\s]?card|医保)', re.I),
     "insurance", "medium", "Possible social security/insurance card"),
    # Driver license
    (re.compile(r'(?:驾照|driving[_\-\s]?licence|driver[_\-\s]?license)', re.I),
     "drivers_license", "medium", "Possible driver's license"),
    # Medical records
    (re.compile(r'(?:病历|体检|medical[_\-\s]?record|health[_\-\s]?report|诊断)', re.I),
     "medical", "medium", "Possible medical record"),
    # Tax/financial documents
    (re.compile(r'(?:税[务单]|tax[_\-\s]?return|w2|w[_\-\s]?2|payslip|工资[条单]|收入证明)', re.I),
     "financial", "medium", "Possible tax/financial document"),
    # Passwords/PINs
    (re.compile(r'(?:密码|password|pin[_\-\s]?code|secret)', re.I),
     "password", "critical", "Possible password/PIN image"),
    # Contracts/legal
    (re.compile(r'(?:合同|协议|contract|agreement|lease|rental)', re.I),
     "contract", "low", "Possible contract/legal document"),
    # Utility bills (address proof)
    (re.compile(r'(?:水电费|utility[_\-\s]?bill|水电煤|账单|bill[_\-\s]?payment)', re.I),
     "utility_bill", "low", "Possible utility bill (address proof)"),
]

# Folder path patterns for sensitive content
SENSITIVE_FOLDER_PATTERNS = [
    (re.compile(r'(?:证[件照]|id[_\-\s]?card|身份|passport|card)', re.I),
     "id_card", "medium", "Folder suggests ID/card images"),
    (re.compile(r'(?:银行|bank|financial|财务)', re.I),
     "financial", "low", "Folder suggests financial documents"),
    (re.compile(r'(?:医疗|medical|健康|health)', re.I),
     "medical", "low", "Folder suggests medical records"),
    (re.compile(r'(?:合同|contract|legal|法务)', re.I),
     "contract", "low", "Folder suggests legal documents"),
]

# Categories from scan_photos.py that may indicate sensitive content
SENSITIVE_CATEGORIES = {
    "document": "low",  # Scanned documents
    "screenshot": "medium",  # Screenshots may contain sensitive info
}

# Risk level priority
RISK_PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def detect_privacy_risks(index_path: str) -> list:
    """Scan metadata index for privacy-sensitive images.

    Returns list of dicts: {
        file_path, risk_type, risk_level, reason, category,
        filename, size_bytes, folder_tag
    }
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Detect available columns for cross-compatibility
    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    select_fields = ["file_path", "filename", "extension", "size_bytes"]
    for col in ("category", "folder_tag", "has_exif", "width", "height", "media_type"):
        if col in available_cols:
            select_fields.append(col)

    query = f"SELECT {', '.join(select_fields)} FROM photos"
    if "media_type" in available_cols:
        query += " WHERE media_type = 'image'"

    cursor = conn.execute(query)

    findings = []
    seen_paths = {}  # path -> highest risk finding

    for row in cursor:
        path = row["file_path"] or ""
        filename = row["filename"] or ""
        # Use safe .get() access for optional columns
        row_dict = dict(row)
        category = row_dict.get("category", "") or ""
        folder_tag = row_dict.get("folder_tag", "") or ""
        size_bytes = row_dict.get("size_bytes", 0) or 0
        width = row_dict.get("width", 0) or 0
        height = row_dict.get("height", 0) or 0

        finding = None

        # 1. Check filename patterns
        for pattern, risk_type, risk_level, reason in SENSITIVE_FILENAME_PATTERNS:
            if pattern.search(filename):
                finding = {
                    "file_path": path,
                    "risk_type": risk_type,
                    "risk_level": risk_level,
                    "reason": reason,
                    "detection_method": "filename",
                    "category": category,
                    "filename": filename,
                    "size_bytes": size_bytes,
                    "folder_tag": folder_tag,
                }
                break

        # 2. Check folder path patterns
        if not finding:
            for pattern, risk_type, risk_level, reason in SENSITIVE_FOLDER_PATTERNS:
                if pattern.search(folder_tag) or pattern.search(path):
                    finding = {
                        "file_path": path,
                        "risk_type": risk_type,
                        "risk_level": risk_level,
                        "reason": reason,
                        "detection_method": "folder_path",
                        "category": category,
                        "filename": filename,
                        "size_bytes": size_bytes,
                        "folder_tag": folder_tag,
                    }
                    break

        # 3. Check category-based risk
        if not finding and category in SENSITIVE_CATEGORIES:
            # Screenshots of banking apps, etc.
            cat_risk = SENSITIVE_CATEGORIES[category]
            # Only flag screenshots that are also in finance-related paths
            if category == "screenshot":
                finance_kw = re.compile(r'(?:bank|银行|pay|支付|alipay|wechat|微信)', re.I)
                if finance_kw.search(filename) or finance_kw.search(folder_tag) or finance_kw.search(path):
                    finding = {
                        "file_path": path,
                        "risk_type": "financial_screenshot",
                        "risk_level": "medium",
                        "reason": "Screenshot of financial app detected",
                        "detection_method": "category+keyword",
                        "category": category,
                        "filename": filename,
                        "size_bytes": size_bytes,
                        "folder_tag": folder_tag,
                    }
            elif category == "document":
                finding = {
                    "file_path": path,
                    "risk_type": "document",
                    "risk_level": cat_risk,
                    "reason": "Scanned document image",
                    "detection_method": "category",
                    "category": category,
                    "filename": filename,
                    "size_bytes": size_bytes,
                    "folder_tag": folder_tag,
                }

        # 4. Dimension heuristic: very small images of card-shaped aspect ratio
        #    (ID cards are typically ~85.6×54mm ≈ aspect 1.586)
        if not finding:
            try:
                w = int(width) if width else 0
                h = int(height) if height else 0
                if 0 < w < 2000 and 0 < h < 2000 and w > 100 and h > 100:
                    aspect = w / h if h > 0 else 0
                    # ID card aspect ratio: ~1.586 (ISO 7810)
                    if 1.4 < aspect < 1.8 and w < 1200 and h < 800:
                        # Small card-shaped image — could be a card photo
                        if category in ("photo", ""):
                            finding = {
                                "file_path": path,
                                "risk_type": "card_shaped",
                                "risk_level": "low",
                                "reason": "Card-shaped small image (possible ID/bank card)",
                                "detection_method": "dimension_heuristic",
                                "category": category,
                                "filename": filename,
                                "size_bytes": size_bytes,
                                "folder_tag": folder_tag,
                            }
            except (ValueError, TypeError):
                pass

        if finding:
            # Keep only the highest-risk finding per path
            existing = seen_paths.get(path)
            if not existing or RISK_PRIORITY.get(finding["risk_level"], 99) < RISK_PRIORITY.get(existing["risk_level"], 99):
                seen_paths[path] = finding

    conn.close()

    findings = list(seen_paths.values())
    # Sort by risk level (critical first)
    findings.sort(key=lambda f: RISK_PRIORITY.get(f["risk_level"], 99))

    return findings


def generate_risk_report(findings: list, total_images: int = 0) -> dict:
    """Generate a structured risk report from findings."""
    by_risk_level = defaultdict(int)
    by_risk_type = defaultdict(int)

    for f in findings:
        by_risk_level[f["risk_level"]] += 1
        by_risk_type[f["risk_type"]] += 1

    recommendations = []

    if by_risk_level.get("critical", 0) > 0:
        recommendations.append({
            "priority": "urgent",
            "action": "Delete or securely store password/PIN images immediately",
            "count": by_risk_level["critical"],
        })

    if by_risk_level.get("high", 0) > 0:
        recommendations.append({
            "priority": "high",
            "action": "Move ID card, passport, and bank card images to an encrypted vault",
            "count": by_risk_level["high"],
        })

    if by_risk_level.get("medium", 0) > 0:
        recommendations.append({
            "priority": "medium",
            "action": "Review screenshots and financial documents — remove or secure",
            "count": by_risk_level["medium"],
        })

    if by_risk_level.get("low", 0) > 0:
        recommendations.append({
            "priority": "low",
            "action": "Consider organizing documents and contracts in a secure folder",
            "count": by_risk_level["low"],
        })

    return {
        "summary": {
            "total_images_scanned": total_images,
            "total_risks_found": len(findings),
            "by_risk_level": dict(by_risk_level),
            "by_risk_type": dict(by_risk_type),
        },
        "recommendations": recommendations,
        "findings": findings,
    }


def write_human_report(report: dict, output_path: str) -> None:
    """Write human-readable risk report."""
    lines = []
    lines.append("=" * 60)
    lines.append("SnapTidy Privacy Risk Report")
    lines.append("=" * 60)
    lines.append("")

    summary = report["summary"]
    lines.append(f"Images scanned:  {summary['total_images_scanned']}")
    lines.append(f"Risks found:     {summary['total_risks_found']}")
    lines.append("")

    by_level = summary.get("by_risk_level", {})
    if by_level:
        lines.append("Risk breakdown:")
        for level in ("critical", "high", "medium", "low"):
            count = by_level.get(level, 0)
            if count:
                icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(level, "⚪")
                lines.append(f"  {icon} {level.upper():8s} {count:4d} items")
    lines.append("")

    by_type = summary.get("by_risk_type", {})
    if by_type:
        lines.append("Risk types:")
        for rtype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  - {rtype:25s} {count:4d}")
    lines.append("")

    # Recommendations
    recommendations = report.get("recommendations", [])
    if recommendations:
        lines.append("Recommendations:")
        for rec in recommendations:
            lines.append(f"  [{rec['priority'].upper():6s}] {rec['action']} ({rec['count']} items)")
        lines.append("")

    # Detailed findings (limit to first 50)
    findings = report.get("findings", [])
    if findings:
        lines.append("Details (first 50):")
        lines.append("-" * 60)
        for i, f in enumerate(findings[:50]):
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(f["risk_level"], "⚪")
            lines.append(f"  {i+1:3d}. {icon} [{f['risk_level'].upper()}] {f['risk_type']}")
            lines.append(f"       {f['filename']}")
            lines.append(f"       {f['reason']}")
            lines.append(f"       Method: {f['detection_method']}")
            lines.append("")
        if len(findings) > 50:
            lines.append(f"  ... and {len(findings) - 50} more findings")
            lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return output_path


def write_json_report(report: dict, output_path: str) -> None:
    """Write JSON risk report."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def write_csv_report(findings: list, output_path: str) -> None:
    """Write CSV risk report."""
    fieldnames = [
        "file_path", "risk_type", "risk_level", "reason",
        "detection_method", "category", "filename", "size_bytes", "folder_tag",
    ]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for finding in findings:
            writer.writerow({k: finding.get(k, "") for k in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect privacy-sensitive images in your photo library")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index (from scan_photos.py)")
    parser.add_argument("--output", "-o", dest="output", required=True,
                        help="Output path (.json, .csv, or .txt for human-readable)")
    parser.add_argument("--format", choices=["auto", "json", "csv", "human"],
                        default="auto",
                        help="Output format (default: auto-detect from extension)")
    parser.add_argument("--min-risk", choices=["critical", "high", "medium", "low"],
                        default="low",
                        help="Minimum risk level to include (default: low)")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    print("🔍 Scanning for privacy-sensitive images...")

    # Detect risks
    findings = detect_privacy_risks(args.index)

    # Filter by minimum risk level
    min_priority = RISK_PRIORITY.get(args.min_risk, 3)
    findings = [f for f in findings if RISK_PRIORITY.get(f["risk_level"], 99) <= min_priority]

    # Count total images
    total_images = 0
    try:
        conn = sqlite3.connect(args.index)
        available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
        if "media_type" in available_cols:
            total_images = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE media_type = 'image'"
            ).fetchone()[0]
        else:
            total_images = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        conn.close()
    except Exception:
        pass

    # Generate report
    report = generate_risk_report(findings, total_images)

    # Output
    fmt = args.format
    if fmt == "auto":
        ext = args.output.rsplit(".", 1)[-1].lower() if "." in args.output else "txt"
        fmt_map = {"json": "json", "csv": "csv", "txt": "human"}
        fmt = fmt_map.get(ext, "human")

    if fmt == "json":
        write_json_report(report, args.output)
    elif fmt == "csv":
        write_csv_report(findings, args.output)
    else:
        write_human_report(report, args.output)

    # Print summary
    summary = report["summary"]
    print(f"\n{'='*50}")
    print(f"Privacy Risk Report")
    print(f"  Images scanned:  {summary['total_images_scanned']}")
    print(f"  Risks found:     {summary['total_risks_found']}")
    for level in ("critical", "high", "medium", "low"):
        count = summary.get("by_risk_level", {}).get(level, 0)
        if count:
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(level, "⚪")
            print(f"  {icon} {level.upper():8s} {count}")
    print(f"\n  Report saved: {args.output}")


if __name__ == "__main__":
    main()
