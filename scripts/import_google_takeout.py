#!/usr/bin/env python3
"""Import photos from Google Takeout export, merging JSON metadata.

Google Photos Takeout exports photos alongside JSON sidecar files containing
metadata (date, GPS, description, albums). This script:

1. Scans a Google Takeout directory for image/video files
2. Finds corresponding .json metadata files
3. Merges metadata (date, GPS, description, title) into the photos
   via EXIF writing or sidecar processing
4. Optionally imports into Photos.app

JSON sidecar naming convention:
  - IMG_0123.jpg → IMG_0123.jpg.json  (or IMG_0123.jpg.supplemental-metadata.json)
  - Photo.jpg → Photo.json
  - Sometimes: Photo(1).jpg → Photo(1).jpg.json

Usage:
    # Scan and merge metadata from Google Takeout
    python3 scripts/import_google_takeout.py \
        --source ~/Downloads/takeout-20250615 \
        --output ./takeout_index.db

    # Also write metadata to EXIF
    python3 scripts/import_google_takeout.py \
        --source ~/Downloads/takeout-20250615 \
        --output ./takeout_index.db \
        --write-exif

    # Import into Photos.app after metadata merge
    python3 scripts/import_google_takeout.py \
        --source ~/Downloads/takeout-20250615 \
        --output ./takeout_index.db \
        --write-exif \
        --import-to-photos \
        --album "Google Import"
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

from constants import IMAGE_EXTS, VIDEO_EXTS, get_format_family, format_size
from photo_metadata import (
    PILLOW_AVAILABLE, PIEXIF_AVAILABLE,
    compute_sha256, get_exif_datetime, get_gps_coords, get_image_size,
    has_exif_data, compute_phash,
)


# ---------------------------------------------------------------------------
# Google Takeout JSON sidecar parsing
# ---------------------------------------------------------------------------

def find_json_sidecar(photo_path: str) -> str:
    """Find the JSON sidecar file for a photo.

    Google Takeout uses several naming conventions:
      photo.jpg.json
      photo.jpg.supplemental-metadata.json  (newer format)
      photo(1).jpg.json

    Returns path to JSON file, or '' if not found.
    """
    candidates = [
        photo_path + ".json",
        # Newer Takeout format
        photo_path + ".supplemental-metadata.json",
    ]

    # Also try the parent directory for sidecar with just the base name
    directory = os.path.dirname(photo_path)
    basename = os.path.basename(photo_path)
    name_without_ext = basename.rsplit(".", 1)[0] if "." in basename else basename
    candidates.append(os.path.join(directory, name_without_ext + ".json"))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return ""


def parse_takeout_json(json_path: str) -> dict:
    """Parse a Google Takeout JSON sidecar file.

    Returns dict with: title, description, date_taken, latitude, longitude,
    album_name, url, photo_taken_time (raw)
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {}

    result = {}

    # Title / filename
    result["title"] = data.get("title", "")

    # Description
    result["description"] = data.get("description", "")

    # GPS coordinates
    geo_data = data.get("geoData", {}) or data.get("geoDataExif", {})
    if geo_data:
        lat = geo_data.get("latitude", 0)
        lon = geo_data.get("longitude", 0)
        if lat and lon and (lat != 0 or lon != 0):
            result["latitude"] = float(lat)
            result["longitude"] = float(lon)
            result["altitude"] = float(geo_data.get("altitude", 0))

    # Date taken (Unix timestamp in seconds)
    taken_time = data.get("photoTakenTime", {})
    if taken_time:
        ts = taken_time.get("timestamp")
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts))
                result["date_taken"] = dt.isoformat()
                result["date_taken_timestamp"] = int(ts)
            except (ValueError, OSError):
                pass

    # Album info
    if "albumData" in data:
        result["album_name"] = data["albumData"].get("title", "")

    # Google Photos URL
    result["url"] = data.get("url", "")

    return result


def merge_takeout_metadata(photo_path: str, takeout_meta: dict) -> bool:
    """Write Takeout metadata into photo's EXIF (requires piexif).

    Sets:
      - DateTimeOriginal (if missing in EXIF but present in Takeout)
      - GPS coordinates (if missing in EXIF but present in Takeout)
      - ImageDescription (from Takeout description)

    Returns True if any changes were made.
    """
    if not PIEXIF_AVAILABLE:
        return False

    import piexif

    try:
        exif_dict = piexif.load(photo_path)
    except Exception:
        return False

    changed = False

    # Set date if missing
    if takeout_meta.get("date_taken_timestamp"):
        existing_dt = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if not existing_dt:
            dt_str = takeout_meta["date_taken"][:19].replace("-", ":").replace("T", " ")
            exif_dict.setdefault("Exif", {})[piexif.ExifIFD.DateTimeOriginal] = dt_str
            changed = True

    # Set GPS if missing
    if takeout_meta.get("latitude") and takeout_meta.get("longitude"):
        existing_gps = exif_dict.get("GPS", {})
        if not existing_gps:
            lat = takeout_meta["latitude"]
            lon = takeout_meta["longitude"]
            # Convert to GPS rational format
            def _to_rational(val):
                if val < 0:
                    val = -val
                deg = int(val)
                minutes = (val - deg) * 60
                return ((deg, 1), (int(minutes), 1), (0, 1))

            lat_ref = b"N" if lat >= 0 else b"S"
            lon_ref = b"E" if lon >= 0 else b"W"

            exif_dict.setdefault("GPS", {})[piexif.GPSIFD.GPSLatitude] = _to_rational(lat)
            exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = _to_rational(lon)
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
            changed = True

    # Set description if present
    if takeout_meta.get("description"):
        desc = takeout_meta["description"][:256]  # Truncate for EXIF
        if isinstance(desc, str):
            desc = desc.encode("utf-8")
        exif_dict.setdefault("0th", {})[piexif.ImageIFD.ImageDescription] = desc
        changed = True

    if changed:
        try:
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, photo_path)
            return True
        except Exception:
            return False

    return False


# ---------------------------------------------------------------------------
# Scanning & indexing
# ---------------------------------------------------------------------------

def scan_takeout_directory(takeout_dir: str, output_db: str,
                           write_exif: bool = False) -> dict:
    """Scan Google Takeout directory and build metadata index.

    Returns stats dict.
    """
    takeout_dir = os.path.abspath(takeout_dir)
    output_db = os.path.abspath(output_db)

    # Initialize DB
    from scan_photos import init_db, _insert_entry

    conn = init_db(output_db)
    scan_time = datetime.now().isoformat()

    # Add takeout-specific columns
    extra_cols = [
        ("takeout_json_path", "TEXT DEFAULT ''"),
        ("takeout_title", "TEXT DEFAULT ''"),
        ("takeout_description", "TEXT DEFAULT ''"),
        ("takeout_date_taken", "TEXT DEFAULT ''"),
        ("takeout_latitude", "REAL DEFAULT 0"),
        ("takeout_longitude", "REAL DEFAULT 0"),
        ("takeout_album", "TEXT DEFAULT ''"),
        ("takeout_url", "TEXT DEFAULT ''"),
    ]
    for col_name, col_type in extra_cols:
        try:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    stats = {"total": 0, "with_json": 0, "exif_written": 0, "errors": 0}

    # Walk directory
    file_list = []
    for root, dirs, files in os.walk(takeout_dir):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                file_list.append((root, name, ext))

    total = len(file_list)
    print(f"Found {total} photo/video files in Takeout")

    for idx, (root, name, ext) in enumerate(file_list):
        if idx % 50 == 0:
            print(f"  Processing... {idx}/{total} ({idx*100//total}%)")

        full_path = os.path.join(root, name)
        stat = os.stat(full_path)

        # Find JSON sidecar
        json_path = find_json_sidecar(full_path)
        takeout_meta = {}
        if json_path:
            takeout_meta = parse_takeout_json(json_path)
            stats["with_json"] += 1

        # Compute basic metadata
        sha256 = compute_sha256(full_path)
        width, height = get_image_size(full_path) if ext in IMAGE_EXTS else ("", "")
        phash = compute_phash(full_path) if ext in IMAGE_EXTS else ""
        has_exif_val = 1 if has_exif_data(full_path) else 0 if ext in IMAGE_EXTS else 0
        exif_dt = get_exif_datetime(full_path) if ext in IMAGE_EXTS else ""
        gps_lat, gps_lon = get_gps_coords(full_path) if ext in IMAGE_EXTS else ("", "")

        # Use Takeout date if EXIF date is missing
        if not exif_dt and takeout_meta.get("date_taken"):
            exif_dt = takeout_meta["date_taken"]

        # Use Takeout GPS if EXIF GPS is missing
        if not gps_lat and takeout_meta.get("latitude"):
            gps_lat = takeout_meta["latitude"]
            gps_lon = takeout_meta["longitude"]

        # Write EXIF if requested
        if write_exif and takeout_meta and ext in IMAGE_EXTS:
            try:
                if merge_takeout_metadata(full_path, takeout_meta):
                    stats["exif_written"] += 1
            except Exception:
                stats["errors"] += 1

        # Build entry
        entry = {
            "file_path": full_path,
            "filename": name,
            "extension": ext,
            "size_bytes": stat.st_size,
            "sha256": sha256,
            "exif_datetime": exif_dt,
            "file_mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "width": width,
            "height": height,
            "phash": phash,
            "media_type": "image" if ext in IMAGE_EXTS else "video",
            "category": "photo",  # Will be refined
            "has_exif": has_exif_val,
            "folder_tag": os.path.basename(root),
            "scan_root": takeout_dir,
            "scanned_at": scan_time,
            "format_family": get_format_family(ext),
        }

        # Add Takeout-specific fields
        if takeout_meta:
            entry["takeout_json_path"] = json_path
            entry["takeout_title"] = takeout_meta.get("title", "")
            entry["takeout_description"] = takeout_meta.get("description", "")
            entry["takeout_date_taken"] = takeout_meta.get("date_taken", "")
            entry["takeout_latitude"] = takeout_meta.get("latitude", 0)
            entry["takeout_longitude"] = takeout_meta.get("longitude", 0)
            entry["takeout_album"] = takeout_meta.get("album_name", "")
            entry["takeout_url"] = takeout_meta.get("url", "")

        _insert_entry(conn, entry)
        conn.commit()
        stats["total"] += 1

    conn.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import photos from Google Takeout export with metadata merge")
    parser.add_argument("--source", "-s", dest="source", required=True,
                        help="Google Takeout directory path")
    parser.add_argument("--output", "-o", dest="output", required=True,
                        help="Output index DB path (.db)")
    parser.add_argument("--write-exif", action="store_true",
                        help="Write Takeout metadata to photo EXIF (date, GPS, description)")
    parser.add_argument("--import-to-photos", action="store_true",
                        help="After indexing, import unique photos into Photos.app")
    parser.add_argument("--album", default="",
                        help="Album name for Photos.app import")
    args = parser.parse_args()

    source = os.path.abspath(args.source)
    if not os.path.isdir(source):
        print(f"Error: {source} is not a directory", file=sys.stderr)
        sys.exit(1)

    output_db = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_db), exist_ok=True)

    print("📥 Scanning Google Takeout directory...")
    stats = scan_takeout_directory(source, output_db, write_exif=args.write_exif)

    print(f"\n{'=' * 50}")
    print(f"Google Takeout Import Complete")
    print(f"  Total files:      {stats['total']}")
    print(f"  With JSON meta:   {stats['with_json']}")
    if args.write_exif:
        print(f"  EXIF updated:     {stats['exif_written']}")
    if stats['errors']:
        print(f"  Errors:           {stats['errors']}")
    print(f"  Index saved:      {output_db}")

    # Optional: import to Photos.app
    if args.import_to_photos:
        print("\n📥 Importing to Photos.app...")
        try:
            from import_to_photos import import_photos
            import_photos(output_db, album=args.album)
        except ImportError:
            print("  Error: import_to_photos module not available", file=sys.stderr)


if __name__ == "__main__":
    main()
