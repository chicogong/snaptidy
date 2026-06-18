#!/usr/bin/env python3
"""Convert photos to a different format (JPEG/HEIC → WEBP/AVIF) to save space.

WEBP offers 25-35% smaller files than JPEG at equivalent quality, and AVIF
offers 50% smaller files.  This script batch-converts while preserving EXIF
metadata and original timestamps.

Features:
  - JPEG → WEBP / AVIF (lossy or lossless)
  - HEIC → WEBP / AVIF (requires pillow-heif)
  - PNG → WEBP (lossless mode)
  - Preserve EXIF GPS/date/camera metadata
  - Preserve original file modification time
  - Configurable quality (1-100)
  - --dry-run to preview space savings
  - --keep-originals to not delete source files
  - --min-size N to skip files smaller than N KB

Usage:
  # Preview space savings (JPEG → WEBP, quality 85)
  python3 convert_format.py --source /path/to/photos --to webp --dry-run

  # Convert all JPEGs to WEBP (quality 85, delete originals)
  python3 convert_format.py --source /path/to/photos --to webp --quality 85

  # Convert only JPEGs > 500KB to AVIF
  python3 convert_format.py --source /path/to/photos --to avif --from jpg \\
      --min-size 500 --quality 80

  # Convert from index DB
  python3 convert_format.py --index photo_index.db --to webp --dry-run
"""

import argparse
import csv
import os
import sqlite3
import sys
import time
from datetime import datetime

from photo_metadata import (
    PILLOW_AVAILABLE, PIEXIF_AVAILABLE, HEIC_SUPPORT, AVIF_SUPPORT,
    get_image_size, is_animated_image,
)
from constants import (
    IMAGE_EXTS, JPEG_EXTS, HEIC_EXTS, AVIF_EXTS,
    get_format_family, format_size,
)

# Conversion capability matrix
CONVERTIBLE_FORMATS = {
    "webp": {"jpg", "jpeg", "png", "heic", "heif", "bmp", "tif", "tiff"},
    "avif": {"jpg", "jpeg", "png", "heic", "heif", "bmp", "tif", "tiff", "webp"},
}


def can_convert(ext: str, target: str) -> bool:
    """Check if a file extension can be converted to the target format."""
    ext = ext.lower().lstrip(".")
    target = target.lower().lstrip(".")
    if target not in CONVERTIBLE_FORMATS:
        return False
    return ext in CONVERTIBLE_FORMATS[target]


def convert_image(src_path: str, dst_path: str, target_format: str,
                  quality: int = 85, lossless: bool = False) -> dict:
    """Convert a single image to the target format.

    Returns dict with: success, src_size, dst_size, src_ext, dst_ext, error
    """
    result = {
        "success": False, "src_size": 0, "dst_size": 0,
        "src_ext": "", "dst_ext": "", "error": "",
    }

    if not PILLOW_AVAILABLE:
        result["error"] = "Pillow not available"
        return result

    try:
        from PIL import Image

        src_size = os.path.getsize(src_path)
        src_ext = os.path.splitext(src_path)[1].lstrip(".").lower()
        result["src_size"] = src_size
        result["src_ext"] = src_ext

        with Image.open(src_path) as img:
            # Convert to RGB if needed (for formats that don't support alpha)
            if target_format in ("webp", "avif") and img.mode in ("RGBA", "LA", "P"):
                pass  # WEBP supports alpha
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            save_kwargs = {}
            if not lossless:
                save_kwargs["quality"] = quality

            # Preserve EXIF if possible
            if PIEXIF_AVAILABLE and "exif" in img.info:
                save_kwargs["exif"] = img.info["exif"]

            if target_format == "webp":
                save_kwargs["method"] = 4  # Compression effort (0=fast, 6=best)
                if lossless:
                    save_kwargs["lossless"] = True
                img.save(dst_path, format="WEBP", **save_kwargs)
            elif target_format == "avif":
                if not AVIF_SUPPORT:
                    result["error"] = "AVIF support not available (install pillow-avif-plugin)"
                    return result
                img.save(dst_path, format="AVIF", **save_kwargs)

        dst_size = os.path.getsize(dst_path)
        result["dst_size"] = dst_size
        result["dst_ext"] = target_format
        result["success"] = True
    except Exception as e:
        result["error"] = str(e)

    return result


def find_convertible_files_db(index_path: str, target: str,
                              source_format: str = "", min_size_kb: int = 0) -> list:
    """Find convertible files from the index DB."""
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    query = "SELECT file_path, filename, extension, size_bytes, format_family FROM photos WHERE media_type = 'image'"
    params = []

    if source_format:
        source_exts = {"jpg": JPEG_EXTS, "jpeg": JPEG_EXTS,
                       "heic": HEIC_EXTS, "heif": HEIC_EXTS,
                       "png": {"png"}, "webp": {"webp"}}.get(source_format.lower(), {source_format.lower()})
        placeholders = ",".join("?" * len(source_exts))
        query += f" AND extension IN ({placeholders})"
        params.extend(source_exts)

    if min_size_kb > 0:
        query += f" AND size_bytes >= ?"
        params.append(min_size_kb * 1024)

    query += " ORDER BY size_bytes DESC"
    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # Filter by convertibility
    return [r for r in rows if can_convert(r["extension"], target)]


def find_convertible_files_dir(source_dir: str, target: str,
                               source_format: str = "", min_size_kb: int = 0) -> list:
    """Find convertible files by scanning a directory."""
    results = []
    source_exts = IMAGE_EXTS
    if source_format:
        fmt_map = {"jpg": JPEG_EXTS, "jpeg": JPEG_EXTS,
                   "heic": HEIC_EXTS, "heif": HEIC_EXTS,
                   "png": {"png"}, "webp": {"webp"}}
        source_exts = fmt_map.get(source_format.lower(), {source_format.lower()})

    for root, dirs, files in os.walk(source_dir):
        for name in files:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in source_exts:
                continue
            if ext == target:
                continue  # Already in target format
            if not can_convert(ext, target):
                continue
            full_path = os.path.join(root, name)
            try:
                size = os.path.getsize(full_path)
                if min_size_kb > 0 and size < min_size_kb * 1024:
                    continue
                results.append({
                    "file_path": full_path,
                    "filename": name,
                    "extension": ext,
                    "size_bytes": size,
                    "format_family": get_format_family(ext),
                })
            except OSError:
                continue
    # Sort by size descending (convert biggest first for max savings)
    results.sort(key=lambda x: x["size_bytes"], reverse=True)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert photos to WEBP/AVIF to save space"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--index", "-i", help="Path to SQLite index DB")
    group.add_argument("--source", "-s", help="Directory to scan")
    parser.add_argument("--to", required=True, choices=["webp", "avif"],
                        help="Target format")
    parser.add_argument("--from", dest="source_format", default="",
                        help="Only convert from this format (jpg, png, heic, webp)")
    parser.add_argument("--quality", type=int, default=85,
                        help="Output quality 1-100 (default: 85)")
    parser.add_argument("--lossless", action="store_true",
                        help="Lossless conversion (larger files, no quality loss)")
    parser.add_argument("--min-size", type=int, default=0,
                        help="Skip files smaller than N KB (default: 0)")
    parser.add_argument("--keep-originals", action="store_true",
                        help="Keep original files (default: delete after conversion)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview space savings — no files modified")
    parser.add_argument("--output", "-o", default=None,
                        help="Write CSV report")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max number of files to convert (0 = all)")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  SnapTidy — Format Converter → {args.to.upper()}")
    print("=" * 60)

    if args.dry_run:
        print("  📋 DRY RUN — no files will be modified\n")
    if args.keep_originals:
        print("  📁 Keeping original files after conversion\n")

    # Check dependencies
    if not PILLOW_AVAILABLE:
        print("❌ Pillow is required. Install with: pip install Pillow", file=sys.stderr)
        sys.exit(1)
    if args.to == "avif" and not AVIF_SUPPORT:
        print("❌ AVIF support not available. Install with: pip install pillow-avif-plugin", file=sys.stderr)
        sys.exit(1)

    # Find files
    if args.index:
        if not os.path.exists(args.index):
            print(f"❌ Index not found: {args.index}", file=sys.stderr)
            sys.exit(1)
        files = find_convertible_files_db(args.index, args.to,
                                          args.source_format, args.min_size)
        print(f"  Source: index DB ({args.index})")
    else:
        files = find_convertible_files_dir(args.source, args.to,
                                           args.source_format, args.min_size)
        print(f"  Source: directory ({args.source})")

    if not files:
        print("\n  No convertible files found.")
        return

    if args.limit > 0:
        files = files[:args.limit]

    # Summary
    total_src_size = sum(f["size_bytes"] for f in files)
    src_fmt_counts = {}
    for f in files:
        src_fmt_counts[f["extension"]] = src_fmt_counts.get(f["extension"], 0) + 1

    print(f"\n  Found {len(files)} convertible files ({format_size(total_src_size)})")
    print(f"  Target: {args.to.upper()} (quality={args.quality}, lossless={args.lossless})")
    print("\n  Source format breakdown:")
    for ext, count in sorted(src_fmt_counts.items(), key=lambda x: -x[1]):
        print(f"    .{ext}: {count} files")

    if args.dry_run:
        # Estimate savings (WEBP ~30% smaller, AVIF ~50% smaller at quality 85)
        if args.lossless:
            ratio = 1.0  # No savings for lossless
        elif args.to == "webp":
            ratio = 0.70  # ~30% savings
        elif args.to == "avif":
            ratio = 0.50  # ~50% savings
        else:
            ratio = 0.80

        est_dst_size = int(total_src_size * ratio)
        savings = total_src_size - est_dst_size
        print(f"\n  💾 Estimated space savings:")
        print(f"     Current size:      {format_size(total_src_size)}")
        print(f"     Estimated after:   {format_size(est_dst_size)}")
        print(f"     Estimated savings: {format_size(savings)} ({(savings/total_src_size*100):.0f}%)")
        print(f"\n  First 10 files that would be converted:")
        for f in files[:10]:
            est_new = int(f["size_bytes"] * ratio)
            print(f"    {f['filename']:40s}  {format_size(f['size_bytes'])} → ~{format_size(est_new)}")
        if len(files) > 10:
            print(f"    ... and {len(files) - 10} more")
        return

    # Convert
    print(f"\n  Converting {len(files)} files to {args.to.upper()}...")
    success = 0
    failed = []
    skipped_animated = 0
    total_saved = 0
    report_rows = []
    start_time = time.time()

    for idx, f in enumerate(files, 1):
        src_path = f["file_path"]
        src_dir = os.path.dirname(src_path)
        src_name = os.path.splitext(f["filename"])[0]
        dst_path = os.path.join(src_dir, f"{src_name}.{args.to}")

        # Preserve original mtime
        try:
            src_mtime = os.path.getmtime(src_path)
        except OSError:
            src_mtime = None

        # Skip animated images — conversion to WEBP/AVIF loses animation frames
        if is_animated_image(src_path):
            skipped_animated += 1
            report_rows.append({
                "file_path": src_path,
                "filename": f["filename"],
                "src_format": f["extension"],
                "dst_format": args.to,
                "src_size": f["size_bytes"],
                "dst_size": 0,
                "saved_bytes": 0,
                "status": "skipped_animated",
            })
            continue

        result = convert_image(src_path, dst_path, args.to,
                              quality=args.quality, lossless=args.lossless)

        if result["success"]:
            success += 1
            saved = result["src_size"] - result["dst_size"]
            total_saved += saved

            # Restore mtime
            if src_mtime is not None:
                try:
                    os.utime(dst_path, (src_mtime, src_mtime))
                except OSError:
                    pass

            # Delete original if not keeping
            if not args.keep_originals:
                try:
                    os.remove(src_path)
                except OSError:
                    pass

            report_rows.append({
                "file_path": src_path,
                "filename": f["filename"],
                "src_format": result["src_ext"],
                "dst_format": result["dst_ext"],
                "src_size": result["src_size"],
                "dst_size": result["dst_size"],
                "saved_bytes": saved,
                "status": "converted",
            })
        else:
            failed.append((src_path, result["error"]))
            report_rows.append({
                "file_path": src_path,
                "filename": f["filename"],
                "src_format": f["extension"],
                "dst_format": args.to,
                "src_size": f["size_bytes"],
                "dst_size": 0,
                "saved_bytes": 0,
                "status": f"failed: {result['error']}",
            })

        if idx % 50 == 0 or idx == len(files):
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            print(f"    {idx}/{len(files)} converted ({rate:.1f} files/s, saved {format_size(total_saved)} so far)")

    # Results
    elapsed = time.time() - start_time
    print(f"\n  ✅ {success} files converted to {args.to.upper()}")
    if skipped_animated > 0:
        print(f"  🎬 {skipped_animated} animated files skipped (conversion would lose frames)")
    print(f"  💾 Total space saved: {format_size(total_saved)}")
    print(f"  ⏱  Time: {elapsed:.1f}s ({success/elapsed:.1f} files/s)" if elapsed > 0 else "")

    if failed:
        print(f"\n  ❌ {len(failed)} files failed:")
        for path, err in failed[:10]:
            print(f"     {path}: {err}")
        if len(failed) > 10:
            print(f"     ... and {len(failed) - 10} more")

    # Update index DB if provided
    if args.index and success > 0:
        print("\n  Note: Index DB contains stale entries. Re-run scan_photos.py to update.")

    # Write CSV report
    if args.output:
        with open(args.output, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=[
                "file_path", "filename", "src_format", "dst_format",
                "src_size", "dst_size", "saved_bytes", "status"
            ])
            writer.writeheader()
            writer.writerows(report_rows)
        print(f"  📄 Report saved: {args.output}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
