#!/usr/bin/env python3
"""Batch-rotate photos to correct orientation based on EXIF Orientation tag.

Many cameras (especially iPhones) store portrait images sideways and set an
EXIF Orientation tag to indicate the correct display rotation.  Some viewers
honour this tag, many do not — causing images to appear sideways or upside
down.

This script reads the EXIF Orientation, physically rotates the pixels to the
correct orientation, and resets the Orientation tag to 1 (Normal).  After
this, the image displays correctly everywhere.

Supports JPEG and TIFF (via piexif).  HEIC is supported if pillow-heif is
installed.

Usage:
  # Preview what would be changed (no files modified)
  python3 rotate_photos.py --index photo_index.db --dry-run

  # Apply rotation to all images with orientation > 1
  python3 rotate_photos.py --index photo_index.db

  # Apply to a specific directory (scan + fix without prior index)
  python3 rotate_photos.py --source /path/to/photos

  # Only fix images with orientation 6 (portrait 90°)
  python3 rotate_photos.py --index photo_index.db --orientation 6
"""

import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime

from photo_metadata import (
    PILLOW_AVAILABLE, PIEXIF_AVAILABLE,
    get_exif_orientation, apply_exif_orientation,
)
from constants import IMAGE_EXTS, JPEG_EXTS, HEIC_EXTS, format_size

# Orientation descriptions for human-readable output
ORIENTATION_NAMES = {
    1: "Normal",
    2: "Mirrored H",
    3: "Rotated 180°",
    4: "Mirrored V",
    5: "Mirrored H + 270°",
    6: "Rotated 90° (portrait)",
    7: "Mirrored H + 90°",
    8: "Rotated 270°",
}


def find_rotated_images_db(index_path: str, orientation_filter: int = 0) -> list:
    """Find images with orientation > 1 from the index DB."""
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    if "orientation" not in available_cols:
        conn.close()
        print("⚠️  'orientation' column not found in index — run scan_photos.py first", file=sys.stderr)
        return []

    if orientation_filter > 0:
        cursor = conn.execute(
            "SELECT file_path, filename, orientation, size_bytes, extension "
            "FROM photos WHERE orientation = ? AND media_type = 'image' "
            "ORDER BY file_path",
            (orientation_filter,)
        )
    else:
        cursor = conn.execute(
            "SELECT file_path, filename, orientation, size_bytes, extension "
            "FROM photos WHERE orientation > 1 AND media_type = 'image' "
            "ORDER BY file_path"
        )

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def find_rotated_images_dir(source_dir: str, orientation_filter: int = 0) -> list:
    """Scan a directory for images with EXIF orientation > 1."""
    if not PILLOW_AVAILABLE or not PIEXIF_AVAILABLE:
        print("⚠️  Pillow and piexif are required for directory scanning", file=sys.stderr)
        print("    pip install Pillow piexif", file=sys.stderr)
        return []

    results = []
    for root, dirs, files in os.walk(source_dir):
        for name in files:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in IMAGE_EXTS:
                continue
            full_path = os.path.join(root, name)
            try:
                # Skip zero-byte files
                if os.path.getsize(full_path) == 0:
                    continue
                orientation = get_exif_orientation(full_path)
                if orientation > 1:
                    if orientation_filter > 0 and orientation != orientation_filter:
                        continue
                    results.append({
                        "file_path": full_path,
                        "filename": name,
                        "orientation": orientation,
                        "size_bytes": os.path.getsize(full_path),
                        "extension": ext,
                    })
            except Exception:
                continue
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Batch-rotate photos to correct EXIF orientation"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--index", "-i", help="Path to SQLite index DB")
    group.add_argument("--source", "-s", help="Directory to scan (no prior index needed)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — no files are modified")
    parser.add_argument("--orientation", type=int, default=0,
                        help="Only fix images with this specific orientation (1-8). "
                             "Default: fix all with orientation > 1")
    parser.add_argument("--output", "-o", default=None,
                        help="Write CSV report of changed files")
    args = parser.parse_args()

    print("=" * 60)
    print("  SnapTidy — Photo Orientation Fixer")
    print("=" * 60)

    if args.dry_run:
        print("  📋 DRY RUN — no files will be modified\n")

    # Find images needing rotation
    if args.index:
        if not os.path.exists(args.index):
            print(f"❌ Index not found: {args.index}", file=sys.stderr)
            sys.exit(1)
        images = find_rotated_images_db(args.index, args.orientation)
        print(f"  Source: index DB ({args.index})")
    else:
        images = find_rotated_images_dir(args.source, args.orientation)
        print(f"  Source: directory ({args.source})")

    if not images:
        print("\n  ✅ No images found with incorrect orientation.")
        return

    # Summary
    orient_counts = {}
    for img in images:
        orient_counts[img["orientation"]] = orient_counts.get(img["orientation"], 0) + 1

    total_size = sum(img["size_bytes"] for img in images)
    print(f"\n  Found {len(images)} images needing rotation ({format_size(total_size)})")
    print("\n  Orientation breakdown:")
    for orient, count in sorted(orient_counts.items()):
        name = ORIENTATION_NAMES.get(orient, f"Unknown ({orient})")
        print(f"    {orient} ({name}): {count} images")

    if args.dry_run:
        print("\n  Files that would be rotated:")
        for img in images[:20]:  # Show first 20
            orient_name = ORIENTATION_NAMES.get(img["orientation"], "Unknown")
            print(f"    [{img['orientation']}] {orient_name:25s}  {img['file_path']}")
        if len(images) > 20:
            print(f"    ... and {len(images) - 20} more")
        print(f"\n  Total: {len(images)} files would be rotated (dry run)")
        return

    # Apply rotation
    print(f"\n  Rotating {len(images)} images...")
    success = 0
    failed = []
    report_rows = []

    for idx, img in enumerate(images, 1):
        path = img["file_path"]
        orient = img["orientation"]
        orient_name = ORIENTATION_NAMES.get(orient, "Unknown")

        ok = apply_exif_orientation(path, quality=95)
        if ok:
            success += 1
            report_rows.append({
                "file_path": path,
                "filename": img["filename"],
                "orientation_before": orient,
                "orientation_after": 1,
                "status": "rotated",
            })
            if idx % 50 == 0 or idx == len(images):
                print(f"    {idx}/{len(images)} processed...")
        else:
            failed.append(path)
            report_rows.append({
                "file_path": path,
                "filename": img["filename"],
                "orientation_before": orient,
                "orientation_after": orient,
                "status": "failed",
            })

    # Results
    print(f"\n  ✅ {success} images rotated successfully")
    if failed:
        print(f"  ❌ {len(failed)} images failed:")
        for f in failed[:10]:
            print(f"     {f}")
        if len(failed) > 10:
            print(f"     ... and {len(failed) - 10} more")

    # Update index DB if provided
    if args.index:
        print("\n  Updating index DB...")
        try:
            conn = sqlite3.connect(args.index)
            for row in report_rows:
                if row["status"] == "rotated":
                    conn.execute(
                        "UPDATE photos SET orientation = 1 WHERE file_path = ?",
                        (row["file_path"],)
                    )
            conn.commit()
            conn.close()
            print(f"  ✅ Index DB updated ({success} rows)")
        except Exception as e:
            print(f"  ⚠️  Failed to update index DB: {e}")

    # Write CSV report
    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "file_path", "filename", "orientation_before",
                "orientation_after", "status"
            ])
            writer.writeheader()
            writer.writerows(report_rows)
        print(f"  📄 Report saved: {args.output}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
