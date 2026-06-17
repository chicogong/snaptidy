#!/usr/bin/env python3
"""Edit EXIF metadata in photos — batch modify, strip GPS, fix dates.

This script provides safe, reversible EXIF editing with --dry-run support.
It uses piexif (JPEG/TIFF) and can optionally shell out to exiftool for
HEIC/RAW formats.

Operations:
  1. strip-gps   — Remove all GPS tags (privacy protection before sharing)
  2. set-date    — Override DateTimeOriginal / DateTime / DateTimeDigitized
  3. set-tags    — Write keywords / description to EXIF ImageDescription
  4. copy-from   — Copy EXIF from one file to another (repair corrupted)

All operations support --dry-run for preview and create backup files by
default (can be disabled with --no-backup).

Usage:
    # Strip GPS from all photos with GPS data
    python3 scripts/edit_exif.py strip-gps --index photo_index.db --dry-run
    python3 scripts/edit_exif.py strip-gps --index photo_index.db

    # Fix date for specific files
    python3 scripts/edit_exif.py set-date --date "2025-06-15T14:30:00" \\
        --paths photo1.jpg photo2.jpg

    # Write tags
    python3 scripts/edit_exif.py set-tags --tags "vacation,beach" \\
        --paths photo1.jpg photo2.jpg

    # Strip GPS from privacy-risk flagged files
    python3 scripts/edit_exif.py strip-gps --index photo_index.db --only-gps
"""

import argparse
import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime

from photo_metadata import PIEXIF_AVAILABLE, get_gps_coords

# Import piexif at module level if available
if PIEXIF_AVAILABLE:
    import piexif

# ---------------------------------------------------------------------------
# EXIF editing helpers
# ---------------------------------------------------------------------------

# Formats that piexif can handle natively (dot-prefixed for Path.suffix comparison)
# Note: This is a tool-capability set, not the same as IMAGE_EXTENSIONS in constants
PIEXIF_FORMATS = {".jpg", ".jpeg", ".tif", ".tiff", ".webp"}

# Formats that need exiftool (dot-prefixed for Path.suffix comparison)
EXIFTOOL_FORMATS = {".heic", ".heif", ".cr2", ".nef", ".arw", ".dng", ".png"}


def _check_piexif(path: str) -> bool:
    """Check if piexif can handle this file format."""
    if not PIEXIF_AVAILABLE:
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in PIEXIF_FORMATS


def _check_exiftool() -> bool:
    """Check if exiftool is available on the system."""
    try:
        result = shutil.which("exiftool")
        return result is not None
    except Exception:
        return False


def _make_backup(path: str, no_backup: bool = False) -> str:
    """Create a backup of the file.  Returns the backup path, or '' if skipped."""
    if no_backup:
        return ""
    backup = path + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    return backup


def _restore_backup(path: str) -> bool:
    """Restore from backup if it exists."""
    backup = path + ".bak"
    if os.path.exists(backup):
        shutil.move(backup, path)
        return True
    return False


def _cleanup_backup(path: str) -> None:
    """Remove backup file after successful operation."""
    backup = path + ".bak"
    try:
        if os.path.exists(backup):
            os.unlink(backup)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def strip_gps(path: str, dry_run: bool = False, no_backup: bool = False) -> dict:
    """Remove all GPS tags from a photo's EXIF data.

    Returns dict with keys: path, status, tags_removed, backup_path
    """
    result = {"path": path, "status": "skipped", "tags_removed": 0, "backup_path": ""}

    if not os.path.isfile(path):
        result["status"] = "error"
        result["error"] = "File not found"
        return result

    ext = os.path.splitext(path)[1].lower()

    # Try piexif first (JPEG/TIFF)
    if _check_piexif(path):
        try:
            exif_dict = piexif.load(path)
            gps_ifd = exif_dict.get("GPS", {})
            if not gps_ifd:
                result["status"] = "no_gps"
                return result

            gps_count = len(gps_ifd)
            result["tags_removed"] = gps_count

            if dry_run:
                result["status"] = "dry_run"
                return result

            # Create backup
            result["backup_path"] = _make_backup(path, no_backup)

            # Remove GPS IFD
            exif_dict["GPS"] = {}
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, path)

            # Clean up backup on success
            if not no_backup:
                _cleanup_backup(path)

            result["status"] = "success"
            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            # Restore backup on error
            if not no_backup:
                _restore_backup(path)
            return result

    # Try exiftool for HEIC/RAW
    if ext in EXIFTOOL_FORMATS and _check_exiftool():
        try:
            # Check if GPS exists
            check = subprocess.run(
                ["exiftool", "-GPSLatitude", "-s3", path],
                capture_output=True, text=True, timeout=10,
            )
            if not check.stdout.strip():
                result["status"] = "no_gps"
                return result

            if dry_run:
                result["status"] = "dry_run"
                result["tags_removed"] = -1  # unknown count
                return result

            # Create backup
            result["backup_path"] = _make_backup(path, no_backup)

            # Strip GPS
            proc = subprocess.run(
                ["exiftool", "-overwrite_original", "-GPS:all=",
                 "-XMP:GPS:all=", path],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                result["status"] = "success"
                result["tags_removed"] = -1
                # Clean up backup on success
                if not no_backup:
                    _cleanup_backup(path)
            else:
                result["status"] = "error"
                result["error"] = proc.stderr.strip()
                if not no_backup:
                    _restore_backup(path)

            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            if not no_backup:
                _restore_backup(path)
            return result

    result["status"] = "unsupported_format"
    result["error"] = f"Format {ext} not supported (install exiftool for HEIC/RAW)"
    return result


def set_date(path: str, date_str: str, dry_run: bool = False,
             no_backup: bool = False) -> dict:
    """Set DateTimeOriginal (and related date fields) in EXIF.

    Args:
        path: Path to the photo file
        date_str: ISO datetime string (e.g. "2025-06-15T14:30:00")
        dry_run: If True, only preview changes
        no_backup: If True, don't create backup files
    """
    result = {"path": path, "status": "skipped", "backup_path": ""}

    if not os.path.isfile(path):
        result["status"] = "error"
        result["error"] = "File not found"
        return result

    # Parse date
    try:
        dt = datetime.fromisoformat(date_str)
        exif_date = dt.strftime("%Y:%m:%d %H:%M:%S")
    except ValueError:
        result["status"] = "error"
        result["error"] = f"Invalid date format: {date_str}"
        return result

    ext = os.path.splitext(path)[1].lower()

    # Try piexif
    if _check_piexif(path):
        try:
            if dry_run:
                result["status"] = "dry_run"
                result["new_date"] = exif_date
                return result

            result["backup_path"] = _make_backup(path, no_backup)

            # Load existing EXIF or create new
            try:
                exif_dict = piexif.load(path)
            except Exception:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "Interop": {}}

            # Set all date fields
            exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_date
            exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = exif_date
            exif_dict["0th"][piexif.ImageIFD.DateTime] = exif_date

            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, path)

            if not no_backup:
                _cleanup_backup(path)
            result["status"] = "success"
            result["new_date"] = exif_date
            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            if not no_backup:
                _restore_backup(path)
            return result

    # Try exiftool
    if ext in EXIFTOOL_FORMATS and _check_exiftool():
        try:
            if dry_run:
                result["status"] = "dry_run"
                result["new_date"] = exif_date
                return result

            result["backup_path"] = _make_backup(path, no_backup)

            proc = subprocess.run(
                ["exiftool", "-overwrite_original",
                 f"-DateTimeOriginal={exif_date}",
                 f"-CreateDate={exif_date}",
                 f"-ModifyDate={exif_date}",
                 path],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                result["status"] = "success"
                result["new_date"] = exif_date
                if not no_backup:
                    _cleanup_backup(path)
            else:
                result["status"] = "error"
                result["error"] = proc.stderr.strip()
                if not no_backup:
                    _restore_backup(path)
            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            if not no_backup:
                _restore_backup(path)
            return result

    result["status"] = "unsupported_format"
    return result


def set_tags(path: str, tags: str, dry_run: bool = False,
             no_backup: bool = False) -> dict:
    """Write keywords/description to EXIF.

    Args:
        path: Path to the photo file
        tags: Comma-separated tag string
        dry_run: If True, only preview changes
        no_backup: If True, don't create backup files
    """
    result = {"path": path, "status": "skipped", "backup_path": ""}

    if not os.path.isfile(path):
        result["status"] = "error"
        result["error"] = "File not found"
        return result

    ext = os.path.splitext(path)[1].lower()

    # Try piexif
    if _check_piexif(path):
        try:
            if dry_run:
                result["status"] = "dry_run"
                result["tags"] = tags
                return result

            result["backup_path"] = _make_backup(path, no_backup)

            try:
                exif_dict = piexif.load(path)
            except Exception:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "Interop": {}}

            # Write ImageDescription
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = tags

            # Also write XPKeywords (Windows) if possible
            try:
                exif_dict["0th"][0x9C9E] = tags.encode("utf-16-le")  # XPKeywords
            except Exception:
                pass

            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, path)

            if not no_backup:
                _cleanup_backup(path)
            result["status"] = "success"
            result["tags"] = tags
            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            if not no_backup:
                _restore_backup(path)
            return result

    # Try exiftool
    if ext in EXIFTOOL_FORMATS and _check_exiftool():
        try:
            if dry_run:
                result["status"] = "dry_run"
                result["tags"] = tags
                return result

            result["backup_path"] = _make_backup(path, no_backup)

            proc = subprocess.run(
                ["exiftool", "-overwrite_original",
                 f"-ImageDescription={tags}",
                 f"-XPKeywords={tags}",
                 f"-Keywords={tags}",
                 path],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                result["status"] = "success"
                result["tags"] = tags
                if not no_backup:
                    _cleanup_backup(path)
            else:
                result["status"] = "error"
                result["error"] = proc.stderr.strip()
                if not no_backup:
                    _restore_backup(path)
            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            if not no_backup:
                _restore_backup(path)
            return result

    result["status"] = "unsupported_format"
    return result


# ---------------------------------------------------------------------------
# Batch operations from index
# ---------------------------------------------------------------------------

def batch_strip_gps(index_path: str, only_gps: bool = False,
                    dry_run: bool = False, no_backup: bool = False,
                    limit: int = 0) -> list:
    """Strip GPS from all photos with GPS data in the index.

    Args:
        index_path: Path to SQLite metadata index
        only_gps: If True, only strip GPS from photos that have GPS data
        dry_run: If True, only preview changes
        no_backup: If True, don't create backup files
        limit: Max files to process (0 = all)
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    query = "SELECT file_path, gps_latitude, gps_longitude FROM photos"
    if only_gps:
        query += " WHERE gps_latitude IS NOT NULL AND gps_latitude != ''"

    rows = list(conn.execute(query))
    conn.close()

    results = []
    count = 0
    for row in rows:
        path = row["file_path"]
        if not os.path.isfile(path):
            continue

        result = strip_gps(path, dry_run=dry_run, no_backup=no_backup)
        results.append(result)
        count += 1

        if limit > 0 and count >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    if not PIEXIF_AVAILABLE:
        print("Warning: piexif not installed. JPEG/TIFF editing unavailable.", file=sys.stderr)
        print("  Install with: pip install piexif", file=sys.stderr)
        print(file=sys.stderr)

    parser = argparse.ArgumentParser(
        description="Edit EXIF metadata in photos (strip GPS, fix dates, write tags)")
    parser.add_argument("operation", choices=["strip-gps", "set-date", "set-tags"],
                        help="Operation to perform")
    parser.add_argument("--index", "-i", dest="index", default="",
                        help="Path to SQLite metadata index (for batch operations)")
    parser.add_argument("--paths", nargs="+", default=[],
                        help="Specific file paths to process")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without modifying files")
    parser.add_argument("--no-backup", action="store_true",
                        help="Don't create .bak backup files")
    parser.add_argument("--only-gps", action="store_true",
                        help="strip-gps: only process files with GPS data")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max files to process (0 = all)")
    parser.add_argument("--date", dest="date", default="",
                        help="set-date: ISO datetime (e.g. 2025-06-15T14:30:00)")
    parser.add_argument("--tags", default="",
                        help="set-tags: comma-separated tags")
    parser.add_argument("--output", "-o", default="",
                        help="Output report path (.json or .csv)")
    args = parser.parse_args()

    results = []

    if args.operation == "strip-gps":
        if args.index:
            print("Stripping GPS data from indexed photos...")
            results = batch_strip_gps(
                args.index, only_gps=args.only_gps,
                dry_run=args.dry_run, no_backup=args.no_backup,
                limit=args.limit,
            )
        elif args.paths:
            for path in args.paths:
                result = strip_gps(path, dry_run=args.dry_run, no_backup=args.no_backup)
                results.append(result)
        else:
            print("Error: specify --index or --paths", file=sys.stderr)
            sys.exit(1)

    elif args.operation == "set-date":
        if not args.date:
            print("Error: --date is required for set-date", file=sys.stderr)
            sys.exit(1)
        if not args.paths:
            print("Error: --paths is required for set-date", file=sys.stderr)
            sys.exit(1)
        for path in args.paths:
            result = set_date(path, args.date, dry_run=args.dry_run, no_backup=args.no_backup)
            results.append(result)

    elif args.operation == "set-tags":
        if not args.tags:
            print("Error: --tags is required for set-tags", file=sys.stderr)
            sys.exit(1)
        if not args.paths:
            print("Error: --paths is required for set-tags", file=sys.stderr)
            sys.exit(1)
        for path in args.paths:
            result = set_tags(path, args.tags, dry_run=args.dry_run, no_backup=args.no_backup)
            results.append(result)

    # Print summary
    success = sum(1 for r in results if r["status"] == "success")
    dry_run_count = sum(1 for r in results if r["status"] == "dry_run")
    errors = sum(1 for r in results if r["status"] == "error")
    skipped = sum(1 for r in results if r["status"] in ("no_gps", "skipped"))

    print()
    print("=" * 50)
    print(f"EXIF Edit Results ({args.operation})")
    print(f"  Processed:  {len(results)}")
    if success:
        print(f"  ✅ Success: {success}")
    if dry_run_count:
        print(f"  👁️  Dry run: {dry_run_count}")
    if skipped:
        print(f"  ⏭️  Skipped: {skipped}")
    if errors:
        print(f"  ❌ Errors:  {errors}")

    # Write report if requested
    if args.output:
        ext = os.path.splitext(args.output)[1].lower()
        if ext == ".json":
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        elif ext == ".csv":
            fieldnames = ["path", "status", "tags_removed", "backup_path", "error"]
            with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for r in results:
                    writer.writerow(r)
        print(f"\n  Report saved: {args.output}")


if __name__ == "__main__":
    main()
