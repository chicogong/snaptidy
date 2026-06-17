#!/usr/bin/env python3
"""Smart photo compression — reduce file size while preserving visual quality.

Analyzes photos in the index DB and compresses oversized files using
intelligent quality settings based on image resolution and content:
  - Large images (>8MP): JPEG quality 85 → typically 60-70% size reduction
  - Medium images (2-8MP): JPEG quality 90 → moderate reduction
  - Small images (<2MP): skip (already small enough)
  - PNG: Convert to JPEG if no transparency (often 80%+ size reduction)
  - HEIC: Skip (already efficient)
  - Never upscale or change resolution

Safety features:
  - --dry-run: preview only, no files modified
  - --backup: keep original files as .orig (default: on)
  - Size threshold: only compress files larger than --min-size (default: 500KB)
  - Quality guard: skip if compressed size > 90% of original (not worth it)

Usage:
    # Preview what would be compressed (no changes)
    python compress_photos.py --index photo_index.db --dry-run

    # Compress oversized photos (>1MB, quality 85)
    python compress_photos.py --index photo_index.db --min-size 1048576 --quality 85

    # Compress and generate report
    python compress_photos.py --index photo_index.db --report compression_report.csv

    # Convert PNG screenshots to JPEG (big savings)
    python compress_photos.py --index photo_index.db --convert-png

    # No backup (original files replaced)
    python compress_photos.py --index photo_index.db --no-backup
"""

import argparse
import csv
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from constants import IMAGE_EXTS, JPEG_EXTS, HEIC_EXTS, format_size
from photo_metadata import PILLOW_AVAILABLE


# ---------------------------------------------------------------------------
# Compression logic
# ---------------------------------------------------------------------------

# Resolution tiers (in megapixels)
TIER_LARGE = 8    # >8MP (e.g., 4000x3000 smartphone photos)
TIER_MEDIUM = 2   # 2-8MP

# Default quality settings per tier
QUALITY_TIERS = {
    "large": 85,    # >8MP: aggressive compression, still looks great
    "medium": 90,   # 2-8MP: moderate compression
    "small": 95,    # <2MP: light compression (mostly not worth it)
}

# Minimum savings threshold (skip if compressed >90% of original)
MIN_SAVINGS_RATIO = 0.90


def should_compress(entry: dict, min_size: int = 512000,
                    convert_png: bool = False) -> tuple:
    """Determine if a photo should be compressed.

    Returns (should_compress: bool, reason: str, target_quality: int).
    """
    ext = (entry.get("extension") or "").lower()
    size = entry.get("size_bytes") or 0

    # Skip non-image files
    if ext not in IMAGE_EXTS:
        return False, "not_image", 0

    # Skip HEIC (already efficient)
    if ext in HEIC_EXTS:
        return False, "heic_efficient", 0

    # Skip files below size threshold
    if size < min_size:
        return False, f"below_{min_size}", 0

    # Get resolution
    width = 0
    height = 0
    try:
        width = int(entry.get("width") or 0)
        height = int(entry.get("height") or 0)
    except (ValueError, TypeError):
        pass

    mp = (width * height) / 1_000_000 if width and height else 0

    # PNG conversion mode
    if ext == "png" and convert_png:
        # PNG → JPEG conversion is usually a huge win for photos
        # But skip if the PNG has transparency
        return True, "png_to_jpeg", QUALITY_TIERS["medium"]

    # JPEG recompression
    if ext in JPEG_EXTS:
        if mp > TIER_LARGE:
            return True, f"large_{mp:.1f}mp", QUALITY_TIERS["large"]
        elif mp > TIER_MEDIUM:
            return True, f"medium_{mp:.1f}mp", QUALITY_TIERS["medium"]
        elif size > min_size * 2:
            # Small but still large file — might be high quality
            return True, f"small_hq_{mp:.1f}mp", QUALITY_TIERS["small"]

    # Other image formats (BMP, TIFF, WebP, etc.)
    if ext in ("bmp", "tif", "tiff") and size > min_size:
        return True, f"convert_{ext}", QUALITY_TIERS["medium"]

    return False, "skip", 0


def compress_image(file_path: str, quality: int, convert_to_jpeg: bool = False,
                   backup: bool = True) -> dict:
    """Compress a single image file.

    Returns dict with compression results:
        {original_size, compressed_size, savings_pct, output_path, error}
    """
    if not PILLOW_AVAILABLE:
        return {"error": "Pillow not installed", "original_size": 0, "compressed_size": 0}

    from PIL import Image

    original_size = os.path.getsize(file_path)
    result = {
        "original_size": original_size,
        "compressed_size": 0,
        "savings_pct": 0,
        "output_path": file_path,
        "error": "",
    }

    try:
        with Image.open(file_path) as img:
            # Check for PNG transparency
            if convert_to_jpeg and img.mode in ("RGBA", "LA", "PA"):
                # Has alpha channel — cannot safely convert to JPEG
                return {**result, "error": "has_transparency"}

            # Convert mode for JPEG
            if convert_to_jpeg or file_path.lower().endswith((".jpg", ".jpeg")):
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")

            # Determine output path
            if convert_to_jpeg:
                output_path = os.path.splitext(file_path)[0] + ".jpg"
            else:
                output_path = file_path

            # Compress to temporary file first
            temp_path = file_path + ".tmp_compress"
            save_kwargs = {"quality": quality, "optimize": True}

            if convert_to_jpeg or output_path.lower().endswith((".jpg", ".jpeg")):
                # Add EXIF orientation for JPEG
                try:
                    from PIL import ImageOps
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass
                img.save(temp_path, "JPEG", **save_kwargs)
            else:
                img.save(temp_path, optimize=True)

            compressed_size = os.path.getsize(temp_path)
            result["compressed_size"] = compressed_size

            # Check if compression is worth it
            ratio = compressed_size / original_size if original_size > 0 else 1.0
            result["savings_pct"] = round((1 - ratio) * 100, 1)

            if ratio > MIN_SAVINGS_RATIO:
                os.unlink(temp_path)
                return {**result, "error": f"insufficient_savings_{result['savings_pct']}%"}

            # Backup original if requested
            if backup and not convert_to_jpeg:
                backup_path = file_path + ".orig"
                if not os.path.exists(backup_path):
                    shutil.copy2(file_path, backup_path)

            # Replace with compressed version
            if convert_to_jpeg and output_path != file_path:
                # New file created
                shutil.move(temp_path, output_path)
                # Optionally remove original
                if backup:
                    if not os.path.exists(file_path + ".orig"):
                        shutil.move(file_path, file_path + ".orig")
                    else:
                        os.unlink(file_path)
                else:
                    os.unlink(file_path)
                result["output_path"] = output_path
            else:
                shutil.move(temp_path, file_path)

            return result

    except Exception as e:
        # Clean up temp file
        temp_path = file_path + ".tmp_compress"
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        return {**result, "error": str(e)[:200]}


def compress_from_index(index_path: str, min_size: int = 512000,
                        quality: int = None, convert_png: bool = False,
                        dry_run: bool = True, backup: bool = True,
                        report_path: str = None) -> dict:
    """Compress photos based on index DB.

    Returns summary dict with counts and stats.
    """
    if not PILLOW_AVAILABLE:
        print("Error: Pillow is required for photo compression.", file=sys.stderr)
        print("       Install with: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Load all images with metadata
    cursor = conn.execute("""
        SELECT file_path, extension, size_bytes, width, height, category
        FROM photos
        WHERE media_type = 'image'
        ORDER BY size_bytes DESC
    """)
    entries = [dict(row) for row in cursor]
    conn.close()

    total = len(entries)
    if total == 0:
        print("No images found in index.")
        return {"total": 0, "compressible": 0, "compressed": 0}

    print(f"Analyzing {total} images for compression...")
    print(f"  Min size: {format_size(min_size)} | PNG conversion: {convert_png} | "
          f"Backup: {backup}")

    # Analyze which files should be compressed
    candidates = []
    skip_reasons = {}
    for entry in entries:
        should, reason, target_q = should_compress(entry, min_size, convert_png)
        if should:
            # Override quality if specified
            final_q = quality if quality is not None else target_q
            candidates.append((entry, reason, final_q))
        else:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    print(f"  Compressible: {len(candidates)}")
    for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"    Skipped ({reason}): {count}")

    if not candidates:
        print("\nNo compressible images found.")
        return {"total": total, "compressible": 0, "compressed": 0}

    # Compress (or dry-run)
    compressed = 0
    errors = 0
    total_original = 0
    total_saved = 0
    report_rows = []
    last_pct = -1

    for idx, (entry, reason, q) in enumerate(candidates):
        pct = idx * 100 // len(candidates)
        if pct >= last_pct + 5 or idx == 0:
            print(f"  Processing... {idx}/{len(candidates)} ({pct}%)")
            last_pct = pct

        file_path = entry["file_path"]
        original_size = entry.get("size_bytes") or 0

        if not os.path.exists(file_path):
            errors += 1
            continue

        is_png_convert = (entry.get("extension") or "").lower() == "png" and convert_png

        if dry_run:
            # Estimate savings based on typical compression ratios
            est_ratio = 0.60 if is_png_convert else 0.75
            est_compressed = int(original_size * est_ratio)
            est_savings = round((1 - est_ratio) * 100, 1)
            report_rows.append({
                "file_path": file_path,
                "extension": entry.get("extension", ""),
                "original_size": original_size,
                "estimated_compressed": est_compressed,
                "estimated_savings": f"{est_savings}%",
                "reason": reason,
                "quality": q,
                "action": "DRY_RUN",
            })
            total_original += original_size
            total_saved += original_size - est_compressed
        else:
            result = compress_image(file_path, q, convert_to_jpeg=is_png_convert,
                                    backup=backup)
            if result.get("error"):
                errors += 1
                report_rows.append({
                    "file_path": file_path,
                    "extension": entry.get("extension", ""),
                    "original_size": original_size,
                    "compressed_size": result.get("compressed_size", 0),
                    "savings": f"{result.get('savings_pct', 0)}%",
                    "reason": reason,
                    "quality": q,
                    "action": f"ERROR: {result['error']}",
                })
            else:
                compressed += 1
                total_original += original_size
                total_saved += original_size - result["compressed_size"]
                report_rows.append({
                    "file_path": file_path,
                    "extension": entry.get("extension", ""),
                    "original_size": original_size,
                    "compressed_size": result["compressed_size"],
                    "savings": f"{result['savings_pct']}%",
                    "reason": reason,
                    "quality": q,
                    "action": "COMPRESSED",
                })

    # Summary
    print(f"\n{'=' * 50}")
    if dry_run:
        print(f"Compression Preview (DRY RUN)")
        print(f"  Compressible: {len(candidates)}")
        print(f"  Estimated savings: {format_size(total_saved)} ({total_saved / max(total_original, 1) * 100:.1f}%)")
    else:
        print(f"Compression Complete")
        print(f"  Compressed: {compressed}/{len(candidates)}")
        print(f"  Errors: {errors}")
        print(f"  Space saved: {format_size(total_saved)} ({total_saved / max(total_original, 1) * 100:.1f}%)")

    # Write report
    if report_path and report_rows:
        with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=report_rows[0].keys())
            writer.writeheader()
            writer.writerows(report_rows)
        print(f"  Report: {report_path}")

    return {
        "total": total,
        "compressible": len(candidates),
        "compressed": compressed if not dry_run else len(candidates),
        "errors": errors,
        "original_bytes": total_original,
        "saved_bytes": total_saved,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Smart photo compression — reduce file size while preserving quality")
    parser.add_argument("--index", "-i", required=True,
                        help="Path to SQLite metadata index (from scan_photos.py)")
    parser.add_argument("--min-size", type=int, default=512000,
                        help="Minimum file size to consider for compression in bytes (default: 512000)")
    parser.add_argument("--quality", "-q", type=int, default=None,
                        help="Override JPEG quality for all files (default: auto 85-95 based on resolution)")
    parser.add_argument("--convert-png", action="store_true",
                        help="Convert PNG photos to JPEG (huge size savings for non-transparent images)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — no files will be modified")
    parser.add_argument("--no-backup", action="store_true",
                        help="Don't keep .orig backup of original files")
    parser.add_argument("--report", "-r", default="",
                        help="Write compression report to CSV")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    compress_from_index(
        os.path.abspath(args.index),
        min_size=args.min_size,
        quality=args.quality,
        convert_png=args.convert_png,
        dry_run=args.dry_run,
        backup=not args.no_backup,
        report_path=os.path.abspath(args.report) if args.report else None,
    )


if __name__ == "__main__":
    main()
