#!/usr/bin/env python3
"""Infer missing GPS coordinates from temporally adjacent photos.

When a burst of photos is taken, some images may lack GPS (e.g. indoor shots
where GPS signal was lost, or photos shared without location).  This script
finds photos with missing GPS and infers coordinates from nearby photos taken
within a configurable time window.

Algorithm:
  1. Load all photos with EXIF datetime from the index DB
  2. Sort by datetime
  3. For each photo missing GPS:
     a. Look at photos taken within ±N minutes (default: 10)
     b. If any have GPS, use the closest one (by time)
     c. If multiple are equally close, average their coordinates
  4. Write inferred GPS to the DB (marked as inferred)
  5. Optionally write to EXIF (--write-exif)

Usage:
  # Preview inferred GPS (no changes)
  python3 fix_gps.py --index photo_index.db --dry-run

  # Write inferred GPS to DB
  python3 fix_gps.py --index photo_index.db

  # Use a wider time window (30 minutes)
  python3 fix_gps.py --index photo_index.db --window 30

  # Also write GPS to EXIF (requires piexif)
  python3 fix_gps.py --index photo_index.db --write-exif
"""

import argparse
import csv
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta

from constants import format_size

# Minimum number of GPS-bearing neighbors required for inference
MIN_GPS_NEIGHBORS = 1

# Maximum distance (km) between inferred location and reference — if the
# nearest GPS-bearing photo is too far in time, the inference is unreliable
MAX_TIME_GAP_MINUTES = 60


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points in km."""
    R = 6371.0
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_photos_from_db(index_path: str):
    """Load photos from DB, returning sorted list of dicts with datetime."""
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    rows = list(conn.execute(
        "SELECT file_path, filename, extension, exif_datetime, "
        "gps_latitude, gps_longitude, size_bytes "
        "FROM photos WHERE media_type = 'image' "
        "AND exif_datetime != '' AND exif_datetime IS NOT NULL "
        "ORDER BY exif_datetime"
    ))
    conn.close()

    photos = []
    for row in rows:
        d = dict(row)
        # Parse datetime
        try:
            d["dt"] = datetime.fromisoformat(d["exif_datetime"])
        except (ValueError, TypeError):
            d["dt"] = None
        # Parse GPS
        try:
            d["lat"] = float(d["gps_latitude"]) if d["gps_latitude"] else None
        except (ValueError, TypeError):
            d["lat"] = None
        try:
            d["lon"] = float(d["gps_longitude"]) if d["gps_longitude"] else None
        except (ValueError, TypeError):
            d["lon"] = None
        photos.append(d)

    # Filter out photos without valid datetime
    photos = [p for p in photos if p["dt"] is not None]
    return photos


def infer_missing_gps(photos: list, window_minutes: int = 10):
    """Find photos with missing GPS and infer from nearby photos.

    Returns list of (photo, inferred_lat, inferred_lon, source_info) tuples.
    """
    window = timedelta(minutes=window_minutes)
    max_gap = timedelta(minutes=MAX_TIME_GAP_MINUTES)

    # Split into GPS-bearing and GPS-missing
    with_gps = [p for p in photos if p["lat"] is not None and p["lon"] is not None]
    without_gps = [p for p in photos if p["lat"] is None or p["lon"] is None]

    if not with_gps or not without_gps:
        return [], with_gps, without_gps

    inferences = []

    for photo in without_gps:
        dt = photo["dt"]

        # Find GPS-bearing photos within the time window
        candidates = []
        for ref in with_gps:
            time_diff = abs((ref["dt"] - dt).total_seconds())
            if time_diff <= window.total_seconds():
                candidates.append((time_diff, ref))

        if not candidates:
            # Try with a larger window (up to MAX_TIME_GAP)
            for ref in with_gps:
                time_diff = abs((ref["dt"] - dt).total_seconds())
                if time_diff <= max_gap.total_seconds():
                    candidates.append((time_diff, ref))

        if not candidates or len(candidates) < MIN_GPS_NEIGHBORS:
            continue

        # Sort by time difference (closest first)
        candidates.sort(key=lambda x: x[0])

        # Use the closest candidates (within 1 minute of each other)
        closest_time = candidates[0][0]
        close_refs = [c for c in candidates if c[0] <= closest_time + 60]

        if len(close_refs) == 1:
            inferred_lat = close_refs[0][1]["lat"]
            inferred_lon = close_refs[0][1]["lon"]
            source = f"from '{close_refs[0][1]['filename']}' ({closest_time:.0f}s away)"
        else:
            # Average coordinates of close references
            lats = [r[1]["lat"] for r in close_refs]
            lons = [r[1]["lon"] for r in close_refs]
            inferred_lat = round(sum(lats) / len(lats), 6)
            inferred_lon = round(sum(lons) / len(lons), 6)
            source = f"averaged from {len(close_refs)} photos ({closest_time:.0f}s away)"

        inferences.append((photo, inferred_lat, inferred_lon, source))

    return inferences, with_gps, without_gps


def write_gps_to_exif(path: str, lat: float, lon: float) -> bool:
    """Write GPS coordinates to EXIF using piexif."""
    try:
        import piexif

        def _to_rational(value):
            """Convert decimal degrees to GPS rational tuple."""
            deg = int(abs(value))
            min_float = (abs(value) - deg) * 60
            minute = int(min_float)
            sec = int((min_float - minute) * 60 * 10000)
            return ((deg, 1), (minute, 1), (sec, 10000))

        exif_dict = piexif.load(path)

        lat_ref = "N" if lat >= 0 else "S"
        lon_ref = "E" if lon >= 0 else "W"

        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = _to_rational(lat)
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref.encode("ascii")
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = _to_rational(lon)
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref.encode("ascii")

        exif_bytes = piexif.dump(exif_dict)

        ext = os.path.splitext(path)[1].lower()
        if ext in (".jpg", ".jpeg", ".tif", ".tiff"):
            piexif.insert(exif_bytes, path)
            return True
        else:
            # For HEIC, we need Pillow
            try:
                from PIL import Image
                with Image.open(path) as img:
                    img.save(path, exif=exif_bytes)
                return True
            except Exception:
                return False
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Infer missing GPS from temporally adjacent photos"
    )
    parser.add_argument("--index", "-i", required=True,
                        help="Path to SQLite index DB")
    parser.add_argument("--window", type=int, default=10,
                        help=f"Time window in minutes to search for neighbors (default: 10, max: {MAX_TIME_GAP_MINUTES})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — no changes to DB or files")
    parser.add_argument("--write-exif", action="store_true",
                        help="Also write inferred GPS to EXIF in the image files")
    parser.add_argument("--output", "-o", default=None,
                        help="Write CSV report of inferred GPS")
    args = parser.parse_args()

    print("=" * 60)
    print("  SnapTidy — GPS Neighbor Inference")
    print("=" * 60)

    if args.dry_run:
        print("  📋 DRY RUN — no changes will be made\n")

    if not os.path.exists(args.index):
        print(f"❌ Index not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    # Load photos
    print(f"\n  Loading photos from index...")
    photos = load_photos_from_db(args.index)
    print(f"  Loaded {len(photos)} photos with EXIF datetime")

    with_gps = [p for p in photos if p["lat"] is not None and p["lon"] is not None]
    without_gps = [p for p in photos if p["lat"] is None or p["lon"] is None]

    print(f"  ✅ {len(with_gps)} photos with GPS coordinates")
    print(f"  ❓ {len(without_gps)} photos missing GPS")

    if not without_gps:
        print("\n  All photos already have GPS. Nothing to infer.")
        return

    if not with_gps:
        print("\n  No photos with GPS found — cannot infer. Need at least one photo with GPS.")
        return

    # Infer
    window = min(args.window, MAX_TIME_GAP_MINUTES)
    print(f"\n  Searching for neighbors within ±{window} minutes...")

    inferences, with_gps, without_gps = infer_missing_gps(photos, window_minutes=window)

    if not inferences:
        print(f"\n  ⚠️  No neighbors found within ±{window} minutes for any missing-GPS photo.")
        print(f"     Try increasing --window (max: {MAX_TIME_GAP_MINUTES})")
        return

    # Report
    print(f"\n  Found {len(inferences)} photos with inferable GPS:")
    for photo, lat, lon, source in inferences[:20]:
        dt_str = photo["dt"].strftime("%Y-%m-%d %H:%M:%S")
        print(f"    [{dt_str}] {photo['filename']}")
        print(f"      → inferred: ({lat}, {lon})")
        print(f"      → source: {source}")

    if len(inferences) > 20:
        print(f"    ... and {len(inferences) - 20} more")

    success_rate = len(inferences) / len(without_gps) * 100 if without_gps else 0
    print(f"\n  Inference rate: {len(inferences)}/{len(without_gps)} ({success_rate:.0f}%)")

    if args.dry_run:
        print("\n  📋 Dry run complete — no changes made.")
        print(f"  Run without --dry-run to apply {len(inferences)} GPS fixes to DB.")
        return

    # Write to DB
    print(f"\n  Writing {len(inferences)} inferred GPS to DB...")
    conn = sqlite3.connect(args.index)
    updated = 0
    for photo, lat, lon, source in inferences:
        try:
            conn.execute(
                "UPDATE photos SET gps_latitude = ?, gps_longitude = ? "
                "WHERE file_path = ?",
                (str(lat), str(lon), photo["file_path"])
            )
            updated += 1
        except Exception as e:
            print(f"  ⚠️  Failed to update {photo['filename']}: {e}")
    conn.commit()
    conn.close()
    print(f"  ✅ {updated} photos updated in DB")

    # Write EXIF if requested
    if args.write_exif:
        print(f"\n  Writing GPS to EXIF files...")
        exif_success = 0
        exif_failed = 0
        for photo, lat, lon, source in inferences:
            if write_gps_to_exif(photo["file_path"], lat, lon):
                exif_success += 1
            else:
                exif_failed += 1
        print(f"  ✅ {exif_success} EXIF updates succeeded")
        if exif_failed:
            print(f"  ❌ {exif_failed} EXIF updates failed (format may not support piexif)")

    # CSV report
    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "file_path", "filename", "exif_datetime",
                "inferred_latitude", "inferred_longitude", "source"
            ])
            writer.writeheader()
            for photo, lat, lon, source in inferences:
                writer.writerow({
                    "file_path": photo["file_path"],
                    "filename": photo["filename"],
                    "exif_datetime": photo["exif_datetime"],
                    "inferred_latitude": lat,
                    "inferred_longitude": lon,
                    "source": source,
                })
        print(f"  📄 Report saved: {args.output}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
