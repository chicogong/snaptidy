#!/usr/bin/env python3
"""Verify photo backup completeness between source and backup directories.

Compares two directories (source vs backup) to find:
  - Missing files: files in source but not in backup
  - Extra files: files in backup but not in source
  - Changed files: files with same relative path but different content

Modes:
  --quick: Compare by filename + size only (fast, may miss renames)
  --full: Compare by SHA-256 hash (slow but accurate, catches renames)

Usage:
  python verify_backup.py --source ~/Photos --backup /Volumes/Backup/Photos [--full] [--report report.csv]
  python verify_backup.py --source ~/Photos --backup /Volumes/Backup/Photos --quick
  python verify_backup.py --index photo_index.db --backup /Volumes/Backup/Photos --full
"""

import argparse
import csv
import hashlib
import os
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".avif", ".raw", ".cr2", ".nef",
    ".arw", ".dng", ".orf", ".rw2", ".raf", ".srw",
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".3gp",
}


def compute_sha256(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return ""


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------

def scan_directory(root: str, full_hash: bool = False) -> dict:
    """Scan a directory and build file index.

    Returns: {relative_path: {path, size, hash}}
    """
    index = {}
    root = os.path.abspath(root)

    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            # Only include photo/video files
            if ext not in PHOTO_EXTENSIONS:
                continue

            full_path = os.path.join(dirpath, fn)
            rel_path = os.path.relpath(full_path, root)

            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue

            entry = {
                "path": full_path,
                "relative_path": rel_path,
                "size": size,
                "hash": "",
            }

            if full_hash:
                entry["hash"] = compute_sha256(full_path)

            index[rel_path] = entry

    return index


def scan_from_index_db(db_path: str) -> dict:
    """Load file index from existing SQLite DB (from scan_photos.py).

    Returns: {relative_path: {path, size, hash}}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT file_path, size_bytes, sha256, scan_root FROM photos"
    ).fetchall()
    conn.close()

    index = {}
    for row in rows:
        fp = row["file_path"]
        scan_root = row["scan_root"] or ""
        rel_path = os.path.relpath(fp, scan_root) if scan_root else os.path.basename(fp)

        index[rel_path] = {
            "path": fp,
            "relative_path": rel_path,
            "size": row["size_bytes"] or 0,
            "hash": row["sha256"] or "",
        }

    return index


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_quick(source: dict, backup: dict) -> dict:
    """Quick comparison: filename + size only."""
    missing = []   # In source but not in backup
    extra = []     # In backup but not in source
    changed = []   # Same relative path, different size

    # Files in source
    for rel_path, entry in source.items():
        if rel_path not in backup:
            missing.append({
                "relative_path": rel_path,
                "source_path": entry["path"],
                "source_size": entry["size"],
            })
        elif entry["size"] != backup[rel_path]["size"]:
            changed.append({
                "relative_path": rel_path,
                "source_path": entry["path"],
                "source_size": entry["size"],
                "backup_path": backup[rel_path]["path"],
                "backup_size": backup[rel_path]["size"],
            })

    # Files only in backup
    for rel_path, entry in backup.items():
        if rel_path not in source:
            extra.append({
                "relative_path": rel_path,
                "backup_path": entry["path"],
                "backup_size": entry["size"],
            })

    return {"missing": missing, "extra": extra, "changed": changed}


def compare_full(source: dict, backup: dict) -> dict:
    """Full comparison using SHA-256 hash. Also catches renamed files."""
    missing = []
    extra = []
    changed = []
    renamed = []   # Files found in backup with different name (by hash)
    matched_by_hash = set()

    # Build hash lookup for backup
    backup_by_hash = defaultdict(list)
    for rel_path, entry in backup.items():
        if entry["hash"]:
            backup_by_hash[entry["hash"]].append(entry)

    # Compare source against backup
    for rel_path, src_entry in source.items():
        src_hash = src_entry["hash"]

        # Same relative path
        if rel_path in backup:
            bk_entry = backup[rel_path]
            if src_hash and bk_entry["hash"] and src_hash == bk_entry["hash"]:
                # Exact match
                matched_by_hash.add(src_hash)
            elif src_hash and bk_entry["hash"] and src_hash != bk_entry["hash"]:
                changed.append({
                    "relative_path": rel_path,
                    "source_path": src_entry["path"],
                    "source_size": src_entry["size"],
                    "source_hash": src_hash,
                    "backup_path": bk_entry["path"],
                    "backup_size": bk_entry["size"],
                    "backup_hash": bk_entry["hash"],
                })
                matched_by_hash.add(src_hash)
            elif src_entry["size"] != bk_entry["size"]:
                # No hash but size differs
                changed.append({
                    "relative_path": rel_path,
                    "source_path": src_entry["path"],
                    "source_size": src_entry["size"],
                    "source_hash": src_hash,
                    "backup_path": bk_entry["path"],
                    "backup_size": bk_entry["size"],
                    "backup_hash": bk_entry["hash"] or "",
                })
        else:
            # Not found by relative path — check by hash (renamed file)
            if src_hash and src_hash in backup_by_hash and src_hash not in matched_by_hash:
                # File exists with different name — this is a rename, not truly missing
                bk_matches = backup_by_hash[src_hash]
                matched_by_hash.add(src_hash)
                renamed.append({
                    "relative_path": rel_path,
                    "source_path": src_entry["path"],
                    "source_size": src_entry["size"],
                    "backup_name": bk_matches[0]["relative_path"],
                    "note": f"Renamed in backup: {bk_matches[0]['relative_path']}",
                })
            else:
                missing.append({
                    "relative_path": rel_path,
                    "source_path": src_entry["path"],
                    "source_size": src_entry["size"],
                    "note": "Not found in backup",
                })

    # Extra files in backup (not in source by path or hash)
    source_hashes = {e["hash"] for e in source.values() if e["hash"]}
    for rel_path, entry in backup.items():
        if rel_path not in source:
            if entry["hash"] and entry["hash"] in source_hashes:
                # File exists in source with different name
                continue  # Already accounted for
            extra.append({
                "relative_path": rel_path,
                "backup_path": entry["path"],
                "backup_size": entry["size"],
            })

    return {"missing": missing, "extra": extra, "changed": changed, "renamed": renamed}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(result: dict, report_path: str):
    """Write comparison report to CSV."""
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["status", "relative_path", "source_path", "backup_path",
                         "source_size", "backup_size", "note"])

        for item in result["missing"]:
            writer.writerow([
                "MISSING_IN_BACKUP", item["relative_path"],
                item.get("source_path", ""), "",
                item.get("source_size", ""), "",
                item.get("note", ""),
            ])

        for item in result["extra"]:
            writer.writerow([
                "EXTRA_IN_BACKUP", item["relative_path"],
                "", item.get("backup_path", ""),
                "", item.get("backup_size", ""),
                item.get("note", ""),
            ])

        for item in result["changed"]:
            writer.writerow([
                "CHANGED", item["relative_path"],
                item.get("source_path", ""), item.get("backup_path", ""),
                item.get("source_size", ""), item.get("backup_size", ""),
                item.get("note", ""),
            ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Verify photo backup completeness between source and backup",
    )
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--source", "-s", help="Source directory to verify")
    src_group.add_argument("--index", "-i", help="Source index DB (from scan_photos.py)")
    parser.add_argument("--backup", "-b", required=True, help="Backup directory to compare against")
    parser.add_argument("--full", action="store_true",
                        help="Full SHA-256 comparison (slower but catches renames)")
    parser.add_argument("--report", "-o", default="", help="Output CSV report")
    args = parser.parse_args()

    if not os.path.exists(args.backup):
        print(f"Error: Backup directory not found: {args.backup}")
        sys.exit(1)

    mode = "FULL (SHA-256)" if args.full else "QUICK (filename+size)"
    print(f"🔄 Backup Verification [{mode}]")

    start = time.time()

    # Build source index
    if args.source:
        print(f"  📂 Scanning source: {args.source}")
        source_index = scan_directory(args.source, full_hash=args.full)
    else:
        print(f"  📂 Loading source index: {args.index}")
        source_index = scan_from_index_db(args.index)
        # If we need hashes and they're missing, compute them
        if args.full:
            missing_hashes = sum(1 for e in source_index.values() if not e["hash"])
            if missing_hashes > 0:
                print(f"  🔢 Computing SHA-256 for {missing_hashes} files without hashes...")
                for rel_path, entry in source_index.items():
                    if not entry["hash"] and os.path.exists(entry["path"]):
                        entry["hash"] = compute_sha256(entry["path"])

    # Build backup index
    print(f"  📂 Scanning backup: {args.backup}")
    backup_index = scan_directory(args.backup, full_hash=args.full)

    elapsed_scan = time.time() - start
    print(f"  Source: {len(source_index)} files, Backup: {len(backup_index)} files "
          f"(scan: {elapsed_scan:.1f}s)")

    # Compare
    print(f"  🔍 Comparing...")
    if args.full:
        result = compare_full(source_index, backup_index)
    else:
        result = compare_quick(source_index, backup_index)

    elapsed = time.time() - start

    # Summary
    n_missing = len(result["missing"])
    n_extra = len(result["extra"])
    n_changed = len(result["changed"])
    n_renamed = len(result.get("renamed", []))

    print(f"\n  ✅ Verification complete in {elapsed:.1f}s")
    print(f"  ❌ Missing in backup: {n_missing}")
    print(f"  ➕ Extra in backup: {n_extra}")
    if n_renamed > 0:
        print(f"  📝 Renamed in backup: {n_renamed}")
    print(f"  🔄 Changed: {n_changed}")

    if n_missing > 0:
        missing_size = sum(item.get("source_size", 0) for item in result["missing"])
        print(f"     Missing total size: {format_size(missing_size)}")
        # Show first 10
        for item in result["missing"][:10]:
            note = f" ({item['note']})" if item.get("note") else ""
            print(f"     - {item['relative_path']}{note}")
        if n_missing > 10:
            print(f"     ... and {n_missing - 10} more")

    if n_extra > 0:
        for item in result["extra"][:5]:
            print(f"     + {item['relative_path']}")
        if n_extra > 5:
            print(f"     ... and {n_extra - 5} more")

    if n_renamed > 0:
        renamed_size = sum(item.get("source_size", 0) for item in result["renamed"])
        print(f"     Renamed total size: {format_size(renamed_size)}")
        for item in result["renamed"][:10]:
            print(f"     = {item['relative_path']} → {item['backup_name']}")
        if n_renamed > 10:
            print(f"     ... and {n_renamed - 10} more")

    if n_changed > 0:
        for item in result["changed"][:5]:
            print(f"     ~ {item['relative_path']}")
        if n_changed > 5:
            print(f"     ... and {n_changed - 5} more")

    # Coverage rate (renamed files count as matched in full mode)
    total_source = len(source_index)
    if total_source > 0:
        matched = total_source - n_missing
        coverage = matched / total_source * 100
        print(f"\n  📊 Backup coverage: {matched}/{total_source} ({coverage:.1f}%)")

    # Write report
    if args.report:
        write_report(result, args.report)
        print(f"  Report → {args.report}")

    return n_missing + n_changed


if __name__ == "__main__":
    sys.exit(main() or 0)
