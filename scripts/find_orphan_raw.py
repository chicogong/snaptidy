#!/usr/bin/env python3
"""Find orphan RAW/JPEG files — RAW without corresponding JPEG, or vice versa.

Photographers often shoot RAW+JPEG pairs. Over time, one side may be deleted
or lost, leaving "orphan" files. This script identifies:

1. Orphan RAW: RAW files without a same-name JPEG in the same directory
2. Orphan JPEG: JPEG files without a same-name RAW in the same directory
   (useful when you deleted the RAW but kept the JPEG, or to find JPEG-only
   exports that lost their RAW master)

Detection: matches files by base name (before extension) in the same directory.
For example:
  - DSC_0001.ARW + DSC_0001.JPG → matched pair
  - DSC_0002.ARW (no DSC_0002.JPG) → orphan RAW
  - DSC_0003.JPG (no DSC_0003.ARW) → orphan JPEG

Usage:
    # Find orphan RAW files
    python3 scripts/find_orphan_raw.py --index photo_index.db --output orphan_raw.csv

    # Find both orphan RAW and orphan JPEG
    python3 scripts/find_orphan_raw.py --index photo_index.db --output orphan_report.csv --both

    # JSON report
    python3 scripts/find_orphan_raw.py --index photo_index.db --output orphan_report.json

    # Only RAW orphans (default)
    python3 scripts/find_orphan_raw.py --index photo_index.db --output orphan_raw.csv --raw-only
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict

from constants import RAW_EXTS, JPEG_EXTS, HEIC_EXTS


def find_orphans(index_path: str, find_raw: bool = True, find_jpeg: bool = False) -> dict:
    """Find orphan RAW/JPEG files.

    Args:
        index_path: Path to SQLite index DB.
        find_raw: Find RAW files without a JPEG/HEIC companion.
        find_jpeg: Find JPEG/HEIC files without a RAW companion.

    Returns:
        {"orphan_raw": [...], "orphan_jpeg": [...], "matched_pairs": [...]}
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute(
        "SELECT file_path, filename, extension, size_bytes, width, height, "
        "       category, camera_make, camera_model, exif_datetime "
        "FROM photos WHERE media_type = 'image'"
    )

    # Group by (directory, base_name)
    by_dir_base = defaultdict(list)
    for row in cursor:
        path = row["file_path"]
        filename = row["filename"] or ""
        ext = (row["extension"] or "").lower()
        directory = os.path.dirname(path)
        base = filename.rsplit(".", 1)[0] if "." in filename else filename

        by_dir_base[(directory, base)].append({
            "path": path,
            "filename": filename,
            "extension": ext,
            "size_bytes": row["size_bytes"] or 0,
            "width": row["width"] or "",
            "height": row["height"] or "",
            "category": row["category"] or "",
            "camera": ((row["camera_make"] or "") + " " + (row["camera_model"] or "")).strip(),
            "date": row["exif_datetime"] or "",
        })

    conn.close()

    orphan_raw = []
    orphan_jpeg = []
    matched_pairs = []

    for (directory, base), files in sorted(by_dir_base.items()):
        raws = [f for f in files if f["extension"] in RAW_EXTS]
        jpegs = [f for f in files if f["extension"] in JPEG_EXTS | HEIC_EXTS]

        if raws and jpegs:
            # Matched pair
            for raw in raws:
                for jpeg in jpegs:
                    matched_pairs.append({
                        "type": "raw_jpeg_pair",
                        "raw_path": raw["path"],
                        "raw_ext": raw["extension"],
                        "raw_size": raw["size_bytes"],
                        "jpeg_path": jpeg["path"],
                        "jpeg_ext": jpeg["extension"],
                        "jpeg_size": jpeg["size_bytes"],
                        "base_name": base,
                        "directory": directory,
                    })
        elif raws and not jpegs:
            # Orphan RAW — no JPEG companion
            if find_raw:
                for raw in raws:
                    orphan_raw.append({
                        "type": "orphan_raw",
                        "path": raw["path"],
                        "filename": raw["filename"],
                        "extension": raw["extension"],
                        "size_bytes": raw["size_bytes"],
                        "width": raw["width"],
                        "height": raw["height"],
                        "camera": raw["camera"],
                        "date": raw["date"],
                        "base_name": base,
                        "directory": directory,
                    })
        elif jpegs and not raws:
            # Orphan JPEG — no RAW companion
            if find_jpeg:
                for jpeg in jpegs:
                    orphan_jpeg.append({
                        "type": "orphan_jpeg",
                        "path": jpeg["path"],
                        "filename": jpeg["filename"],
                        "extension": jpeg["extension"],
                        "size_bytes": jpeg["size_bytes"],
                        "width": jpeg["width"],
                        "height": jpeg["height"],
                        "camera": jpeg["camera"],
                        "date": jpeg["date"],
                        "base_name": base,
                        "directory": directory,
                    })

    return {
        "orphan_raw": orphan_raw,
        "orphan_jpeg": orphan_jpeg,
        "matched_pairs": matched_pairs,
    }


def write_report(results: dict, output_path: str) -> None:
    """Write orphan report to CSV or JSON."""
    ext = output_path.rsplit(".", 1)[-1].lower() if "." in output_path else "csv"

    if ext == "json":
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    else:
        # Combine orphan_raw + orphan_jpeg + matched_pairs into one CSV
        rows = []
        for item in results.get("orphan_raw", []):
            item["category"] = "orphan_raw"
            rows.append(item)
        for item in results.get("orphan_jpeg", []):
            item["category"] = "orphan_jpeg"
            rows.append(item)
        for item in results.get("matched_pairs", []):
            item["category"] = "raw_jpeg_pair"
            rows.append(item)

        if rows:
            fieldnames = list(rows[0].keys())
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find orphan RAW/JPEG files — RAW without JPEG companion or vice versa")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index")
    parser.add_argument("--output", "-o", dest="output", required=True,
                        help="Output report path (.csv or .json)")
    parser.add_argument("--raw-only", action="store_true", default=True,
                        help="Only find orphan RAW files (default)")
    parser.add_argument("--both", action="store_true",
                        help="Find both orphan RAW and orphan JPEG files")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    find_jpeg = args.both
    print("🔍 Scanning for orphan RAW/JPEG files...")

    results = find_orphans(
        os.path.abspath(args.index),
        find_raw=True,
        find_jpeg=find_jpeg,
    )

    output_path = os.path.abspath(args.output)
    write_report(results, output_path)

    n_orphan_raw = len(results["orphan_raw"])
    n_orphan_jpeg = len(results["orphan_jpeg"])
    n_pairs = len(results["matched_pairs"])

    # Compute orphan RAW total size
    total_raw_size = sum(r["size_bytes"] for r in results["orphan_raw"])

    print(f"\n{'=' * 50}")
    print(f"Orphan RAW/JPEG Report")
    print(f"  Matched RAW+JPEG pairs: {n_pairs}")
    print(f"  Orphan RAW files:       {n_orphan_raw}")
    if find_jpeg:
        print(f"  Orphan JPEG files:      {n_orphan_jpeg}")
    if total_raw_size > 0:
        if total_raw_size >= 1_073_741_824:
            print(f"  Orphan RAW size:        {total_raw_size / 1_073_741_824:.1f} GB")
        elif total_raw_size >= 1_048_576:
            print(f"  Orphan RAW size:        {total_raw_size / 1_048_576:.1f} MB")
        else:
            print(f"  Orphan RAW size:        {total_raw_size / 1_024:.1f} KB")
    print(f"\n  Report saved: {output_path}")


if __name__ == "__main__":
    main()
