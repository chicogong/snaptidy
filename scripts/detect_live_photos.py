#!/usr/bin/env python3
"""Detect Live Photo pairs in a photo library.

Live Photos on iPhone consist of a HEIC/JPEG still image + a short MOV video
with the same base filename. This script scans the metadata index (SQLite DB)
and identifies these pairs, writing a `live_photo_group` column so that:
  - Dedup tools keep both parts of a Live Photo together
  - The review page can show Live Photo badges
  - Move plans never split a Live Photo pair

Detection methods:
1. Filename matching: IMG_0123.HEIC + IMG_0123.MOV (same base, image+video)
2. Photos.sqlite reference: ZADDITIONALASSETATTRIBUTES.ZPLAYBACKVARIANT = 2
   indicates a Live Photo component (only for library scans)

Usage:
    # Detect Live Photo pairs in a file-system index
    python3 scripts/detect_live_photos.py --index photo_index.db

    # Incremental (only process unpaired photos)
    python3 scripts/detect_live_photos.py --index photo_index.db --incremental

    # Export pairs report
    python3 scripts/detect_live_photos.py --index photo_index.db --report live_photos.json
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

from constants import IMAGE_EXTS, VIDEO_EXTS, JPEG_EXTS, HEIC_EXTS


# ---------------------------------------------------------------------------
# Live Photo pair detection
# ---------------------------------------------------------------------------

# Live Photo video filenames match their still image counterparts:
#   IMG_0123.HEIC + IMG_0123.MOV
#   IMG_0123.JPG  + IMG_0123.MOV
#   IMG_0123.PNG  + IMG_0123.MOV  (unlikely but handle)
LIVE_PHOTO_VIDEO_EXTS = {"mov", "mp4", "m4v"}

# Still image extensions that can be Live Photo components
LIVE_PHOTO_IMAGE_EXTS = HEIC_EXTS | JPEG_EXTS

# Common Live Photo base filename patterns
# IMG_0001, FULL_0001, DSC_0001, etc.
LIVE_PHOTO_BASE_RE = re.compile(
    r"^(IMG|FULL|DSC|DSCF|P|_)\d+", re.IGNORECASE
)


def find_live_photo_pairs(index_path: str, incremental: bool = False) -> list:
    """Find Live Photo pairs in the index.

    Returns list of dicts: {group_id, image_path, video_path, base_name, method}
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Check for live_photo_group column
    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    # Load all files
    query = "SELECT file_path, filename, extension, media_type, category FROM photos"
    if incremental and "live_photo_group" in available_cols:
        query += " WHERE live_photo_group = '' OR live_photo_group IS NULL"

    cursor = conn.execute(query)
    rows = cursor.fetchall()

    # Build lookup: base_name (without ext) -> list of (path, ext, media_type)
    by_base = defaultdict(list)
    for row in rows:
        path = row["file_path"]
        filename = row["filename"]
        ext = (row["extension"] or "").lower()
        media_type = row["media_type"] or ""

        # Split filename into base + extension
        if "." in filename:
            base = filename.rsplit(".", 1)[0]
        else:
            base = filename

        by_base[base].append({
            "path": path,
            "ext": ext,
            "media_type": media_type,
            "filename": filename,
        })

    # Find pairs: same base name, one image + one video
    pairs = []
    group_id = 0

    for base, files in sorted(by_base.items()):
        images = [f for f in files if f["media_type"] == "image"
                  and f["ext"] in LIVE_PHOTO_IMAGE_EXTS]
        videos = [f for f in files if f["media_type"] == "video"
                  and f["ext"] in LIVE_PHOTO_VIDEO_EXTS]

        if images and videos:
            # Found a Live Photo pair
            for img in images:
                for vid in videos:
                    # Extra check: same directory
                    img_dir = os.path.dirname(img["path"])
                    vid_dir = os.path.dirname(vid["path"])
                    if img_dir != vid_dir:
                        continue

                    group_id += 1
                    pairs.append({
                        "group_id": f"live_{group_id}",
                        "image_path": img["path"],
                        "video_path": vid["path"],
                        "base_name": base,
                        "method": "filename_match",
                    })

    conn.close()
    return pairs


def write_pairs_to_db(index_path: str, pairs: list) -> int:
    """Write live_photo_group column to DB. Returns number of files updated."""
    conn = sqlite3.connect(index_path)

    # Add column if not exists
    try:
        conn.execute("ALTER TABLE photos ADD COLUMN live_photo_group TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_live_photo_group ON photos(live_photo_group)")
    except sqlite3.OperationalError:
        pass

    updated = 0
    for pair in pairs:
        gid = pair["group_id"]
        conn.execute("UPDATE photos SET live_photo_group = ? WHERE file_path = ?",
                     (gid, pair["image_path"]))
        conn.execute("UPDATE photos SET live_photo_group = ? WHERE file_path = ?",
                     (gid, pair["video_path"]))
        updated += 2

    conn.commit()
    conn.close()
    return updated


def generate_report(pairs: list, index_path: str) -> dict:
    """Generate a summary report of Live Photo detection."""
    # Load metadata for report
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    metadata = {}
    for row in conn.execute("SELECT * FROM photos"):
        metadata[row["file_path"]] = dict(row)
    conn.close()

    report_pairs = []
    for pair in pairs:
        img_meta = metadata.get(pair["image_path"], {})
        vid_meta = metadata.get(pair["video_path"], {})

        report_pairs.append({
            "group_id": pair["group_id"],
            "base_name": pair["base_name"],
            "method": pair["method"],
            "image": {
                "path": pair["image_path"],
                "filename": img_meta.get("filename", ""),
                "size_bytes": img_meta.get("size_bytes", 0),
                "extension": img_meta.get("extension", ""),
            },
            "video": {
                "path": pair["video_path"],
                "filename": vid_meta.get("filename", ""),
                "size_bytes": vid_meta.get("size_bytes", 0),
                "extension": vid_meta.get("extension", ""),
            },
        })

    return {
        "total_pairs": len(pairs),
        "method": "filename_match",
        "pairs": report_pairs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect Live Photo pairs (image + short video) in photo library")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index (from scan_photos.py)")
    parser.add_argument("--incremental", action="store_true",
                        help="Only process photos without live_photo_group value")
    parser.add_argument("--report", "-r", dest="report", default="",
                        help="Export Live Photo pairs report (.json or .csv)")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    index_path = os.path.abspath(args.index)

    print("🔍 Detecting Live Photo pairs...")
    pairs = find_live_photo_pairs(index_path, incremental=args.incremental)

    if not pairs:
        print("No Live Photo pairs found.")
        return

    # Write to DB
    updated = write_pairs_to_db(index_path, pairs)

    # Generate report
    if args.report:
        report_path = os.path.abspath(args.report)
        report = generate_report(pairs, index_path)
        ext = report_path.rsplit(".", 1)[-1].lower() if "." in report_path else "json"
        if ext == "csv":
            fieldnames = ["group_id", "base_name", "method", "image_path", "video_path"]
            flat_pairs = []
            for p in pairs:
                flat_pairs.append({
                    "group_id": p["group_id"],
                    "base_name": p["base_name"],
                    "method": p["method"],
                    "image_path": p["image_path"],
                    "video_path": p["video_path"],
                })
            with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(flat_pairs)
        else:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"  Report saved: {report_path}")

    print(f"\n{'=' * 50}")
    print(f"Live Photo Detection Complete")
    print(f"  Pairs found:    {len(pairs)}")
    print(f"  Files updated:  {updated}")
    print(f"  Column:         live_photo_group")


if __name__ == "__main__":
    main()
