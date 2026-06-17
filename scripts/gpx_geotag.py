#!/usr/bin/env python3
"""Geotag photos from GPX track files — assign GPS to photos without coordinates.

Reads a GPX track file and matches timestamps to assign latitude/longitude
to photos that lack GPS data. Useful for DSLR photos shot without GPS,
where you carried a phone/GPS tracker simultaneously.

Matching logic:
  - Reads photo's EXIF DateTimeOriginal
  - Finds closest GPX trackpoint by timestamp
  - Interpolates position between adjacent trackpoints
  - Accepts matches within a configurable time tolerance (default: 30s)

GPX format: Standard GPS Exchange Format (XML).
  - Parses <trkpt lat="..." lon="..."><time>...</time></trkpt>
  - Handles multiple tracks and track segments

Usage:
    # Geotag photos from a GPX track
    python3 scripts/gpx_geotag.py \
        --index photo_index.db \
        --gpx track.gpx \
        --tolerance 30

    # Preview only (dry-run, don't write to DB or EXIF)
    python3 scripts/gpx_geotag.py \
        --index photo_index.db \
        --gpx track.gpx \
        --dry-run

    # Also write GPS to EXIF
    python3 scripts/gpx_geotag.py \
        --index photo_index.db \
        --gpx track.gpx \
        --write-exif

    # Larger tolerance for cameras with wrong timezone
    python3 scripts/gpx_geotag.py \
        --index photo_index.db \
        --gpx track.gpx \
        --tolerance 300 \
        --timezone-offset +8
"""

import argparse
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from photo_metadata import PIEXIF_AVAILABLE


# ---------------------------------------------------------------------------
# GPX parsing
# ---------------------------------------------------------------------------

def parse_gpx(gpx_path: str) -> list:
    """Parse GPX file and extract trackpoints.

    Returns list of (datetime, lat, lon) sorted by time.
    """
    try:
        tree = ET.parse(gpx_path)
    except ET.ParseError as e:
        print(f"Error parsing GPX: {e}", file=sys.stderr)
        return []

    root = tree.getroot()
    # Handle GPX namespace
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    trackpoints = []

    for trkpt in root.iter(f"{ns}trkpt"):
        lat = trkpt.get("lat")
        lon = trkpt.get("lon")
        if not lat or not lon:
            continue

        time_elem = trkpt.find(f"{ns}time")
        if time_elem is None or not time_elem.text:
            continue

        # Parse ISO 8601 time
        time_str = time_elem.text.strip()
        # Handle various formats: 2025-06-15T08:30:45Z, 2025-06-15T08:30:45+08:00
        time_str = time_str.rstrip("Z")
        if "+" in time_str[10:]:
            time_str = time_str[:time_str.index("+", 10)]
        try:
            dt = datetime.fromisoformat(time_str)
        except ValueError:
            continue

        trackpoints.append((dt, float(lat), float(lon)))

    trackpoints.sort(key=lambda x: x[0])
    return trackpoints


def find_closest_position(trackpoints: list, photo_time: datetime,
                          tolerance_seconds: int = 30) -> tuple:
    """Find the closest GPX position for a given photo timestamp.

    Returns (lat, lon) or (None, None) if no match within tolerance.
    Uses linear interpolation between adjacent trackpoints.
    """
    if not trackpoints:
        return None, None

    # Binary search for closest trackpoint
    best_idx = 0
    best_diff = abs((photo_time - trackpoints[0][0]).total_seconds())

    for i in range(1, len(trackpoints)):
        diff = abs((photo_time - trackpoints[i][0]).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_idx = i

    # Check tolerance
    if best_diff > tolerance_seconds:
        return None, None

    # Try interpolation with adjacent trackpoint
    tp_time, tp_lat, tp_lon = trackpoints[best_idx]

    # Check if we can interpolate with the next trackpoint
    if best_idx + 1 < len(trackpoints):
        next_time, next_lat, next_lon = trackpoints[best_idx + 1]
        # Only interpolate if photo time is between these two points
        if tp_time <= photo_time <= next_time:
            total_secs = (next_time - tp_time).total_seconds()
            if total_secs > 0:
                ratio = (photo_time - tp_time).total_seconds() / total_secs
                lat = tp_lat + (next_lat - tp_lat) * ratio
                lon = tp_lon + (next_lon - tp_lon) * ratio
                return round(lat, 6), round(lon, 6)

    # Check previous trackpoint for interpolation
    if best_idx > 0:
        prev_time, prev_lat, prev_lon = trackpoints[best_idx - 1]
        if prev_time <= photo_time <= tp_time:
            total_secs = (tp_time - prev_time).total_seconds()
            if total_secs > 0:
                ratio = (photo_time - prev_time).total_seconds() / total_secs
                lat = prev_lat + (tp_lat - prev_lat) * ratio
                lon = prev_lon + (tp_lon - prev_lon) * ratio
                return round(lat, 6), round(lon, 6)

    # No interpolation possible, use closest point directly
    return round(tp_lat, 6), round(tp_lon, 6)


# ---------------------------------------------------------------------------
# Geotagging
# ---------------------------------------------------------------------------

def geotag_from_gpx(index_path: str, gpx_path: str, tolerance: int = 30,
                    timezone_offset: int = 0, write_exif: bool = False,
                    dry_run: bool = False) -> dict:
    """Geotag photos without GPS using GPX track data.

    Returns stats dict.
    """
    # Parse GPX
    trackpoints = parse_gpx(gpx_path)
    if not trackpoints:
        print("No trackpoints found in GPX file.", file=sys.stderr)
        return {"matched": 0, "total_no_gps": 0}

    print(f"  Loaded {len(trackpoints)} trackpoints from GPX")
    print(f"  Time range: {trackpoints[0][0]} → {trackpoints[-1][0]}")

    # Apply timezone offset
    if timezone_offset:
        offset = timedelta(hours=timezone_offset)
        trackpoints = [(t + offset, lat, lon) for t, lat, lon in trackpoints]

    # Find photos without GPS
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Get photos with date but no GPS
    cursor = conn.execute("""
        SELECT file_path, filename, extension, exif_datetime, file_mtime
        FROM photos
        WHERE media_type = 'image'
          AND (gps_latitude = '' OR gps_latitude IS NULL OR gps_latitude = '0')
          AND exif_datetime != ''
    """)

    rows = cursor.fetchall()
    total_no_gps = len(rows)
    matched = 0
    exif_written = 0

    print(f"  Photos without GPS: {total_no_gps}")

    for row in rows:
        dt_str = row["exif_datetime"]
        try:
            photo_time = datetime.fromisoformat(dt_str)
        except ValueError:
            continue

        lat, lon = find_closest_position(trackpoints, photo_time, tolerance)
        if lat is not None:
            matched += 1

            if not dry_run:
                # Update DB
                conn.execute(
                    "UPDATE photos SET gps_latitude = ?, gps_longitude = ? WHERE file_path = ?",
                    (str(lat), str(lon), row["file_path"]),
                )

                # Write to EXIF if requested
                if write_exif and PIEXIF_AVAILABLE:
                    try:
                        import piexif
                        exif_dict = piexif.load(row["file_path"])

                        def _to_rational(val):
                            if val < 0:
                                val = -val
                            deg = int(val)
                            minutes = (val - deg) * 60
                            return ((deg, 1), (int(minutes), 1), (0, 1))

                        exif_dict.setdefault("GPS", {})[piexif.GPSIFD.GPSLatitude] = _to_rational(lat)
                        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"N" if lat >= 0 else b"S"
                        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = _to_rational(lon)
                        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = b"E" if lon >= 0 else b"W"

                        exif_bytes = piexif.dump(exif_dict)
                        piexif.insert(exif_bytes, row["file_path"])
                        exif_written += 1
                    except Exception:
                        pass

    if not dry_run:
        conn.commit()
    conn.close()

    return {
        "matched": matched,
        "total_no_gps": total_no_gps,
        "exif_written": exif_written,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Geotag photos from GPX track files")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index")
    parser.add_argument("--gpx", "-g", dest="gpx", required=True,
                        help="Path to GPX track file")
    parser.add_argument("--tolerance", "-t", type=int, default=30,
                        help="Max seconds between photo time and trackpoint (default: 30)")
    parser.add_argument("--timezone-offset", type=int, default=0,
                        help="Hours to offset GPX timestamps (e.g., +8 for CST)")
    parser.add_argument("--write-exif", action="store_true",
                        help="Also write GPS to photo EXIF")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview matches without writing to DB or EXIF")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index not found: {args.index}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.gpx):
        print(f"Error: GPX file not found: {args.gpx}", file=sys.stderr)
        sys.exit(1)

    print("🗺️ Geotagging photos from GPX track...")
    stats = geotag_from_gpx(
        os.path.abspath(args.index),
        os.path.abspath(args.gpx),
        tolerance=args.tolerance,
        timezone_offset=args.timezone_offset,
        write_exif=args.write_exif,
        dry_run=args.dry_run,
    )

    print(f"\n{'=' * 50}")
    print(f"GPX Geotagging Report")
    print(f"  Photos without GPS: {stats['total_no_gps']}")
    print(f"  Matched to track:   {stats['matched']}")
    if args.write_exif:
        print(f"  EXIF updated:       {stats['exif_written']}")
    if args.dry_run:
        print(f"  Mode: DRY RUN (no changes written)")
    else:
        print(f"  GPS coordinates written to: {args.index}")


if __name__ == "__main__":
    main()
