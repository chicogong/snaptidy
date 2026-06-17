#!/usr/bin/env python3
"""Cluster photos into events by time and location proximity.

Groups photos into meaningful events (e.g., "北京三日游", "周末野餐") using:
  - Time gaps: consecutive photos >N hours apart start a new event
  - Location changes: photos in different cities belong to different events
  - Day boundaries: events don't cross midnight by default

Useful for:
  - Organizing photos into event-based albums
  - Understanding your photo timeline at a glance
  - Generating event-based reports

Usage:
    # Cluster photos with default settings (4-hour gap threshold)
    python3 scripts/cluster_events.py --index photo_index.db --output events.json

    # Custom gap threshold (2 hours)
    python3 scripts/cluster_events.py --index photo_index.db --output events.json --gap-hours 2

    # Include location in clustering
    python3 scripts/cluster_events.py --index photo_index.db --output events.json --use-location

    # Also write event labels back to DB
    python3 scripts/cluster_events.py --index photo_index.db --output events.json --write-db
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from constants import format_size


def load_photos_sorted(index_path: str) -> list:
    """Load photos with date and location, sorted by date.

    Returns list of dicts sorted by exif_datetime.
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    select_fields = ["file_path", "filename", "extension", "size_bytes",
                     "exif_datetime", "file_mtime", "category", "media_type",
                     "place_city", "place_country"]
    for col in ("camera_make", "camera_model", "gps_latitude", "gps_longitude", "width", "height"):
        if col in available_cols:
            select_fields.append(col)

    query = f"SELECT {', '.join(select_fields)} FROM photos WHERE media_type = 'image'"

    cursor = conn.execute(query)
    rows = [dict(row) for row in cursor]
    conn.close()

    # Sort by date
    def sort_key(r):
        dt = r.get("exif_datetime") or r.get("file_mtime") or ""
        return dt

    rows.sort(key=sort_key)
    return rows


def cluster_events(photos: list, gap_hours: float = 4.0,
                   use_location: bool = False,
                   split_days: bool = True) -> list:
    """Cluster photos into events.

    Args:
        photos: List of photo dicts, sorted by date.
        gap_hours: Minimum gap between events in hours.
        use_location: If True, different cities always start new events.
        split_days: If True, events don't cross midnight.

    Returns:
        List of event dicts: {event_id, start_date, end_date, city, country,
                              photo_count, size_bytes, photos: [...]}
    """
    if not photos:
        return []

    events = []
    current_event = None
    event_id = 0

    gap = timedelta(hours=gap_hours)

    for photo in photos:
        dt_str = photo.get("exif_datetime") or photo.get("file_mtime") or ""
        if not dt_str:
            continue

        try:
            photo_dt = datetime.fromisoformat(dt_str[:19])
        except ValueError:
            continue

        city = photo.get("place_city") or ""
        country = photo.get("place_country") or ""

        # Determine if this photo starts a new event
        start_new = False

        if current_event is None:
            start_new = True
        else:
            last_dt = current_event["end_dt"]
            time_diff = photo_dt - last_dt

            # Time gap exceeded
            if time_diff > gap:
                start_new = True

            # Day boundary crossed
            if split_days and photo_dt.date() != last_dt.date():
                start_new = True

            # Location change
            if use_location and city and current_event.get("city") and city != current_event["city"]:
                start_new = True

        if start_new:
            # Finalize previous event
            if current_event:
                _finalize_event(current_event)
                events.append(current_event)

            # Start new event
            event_id += 1
            current_event = {
                "event_id": f"event_{event_id:03d}",
                "start_date": photo_dt.isoformat(),
                "end_date": photo_dt.isoformat(),
                "start_dt": photo_dt,
                "end_dt": photo_dt,
                "city": city,
                "country": country,
                "photo_count": 0,
                "size_bytes": 0,
                "photos": [],
            }

        # Add photo to current event
        current_event["end_date"] = photo_dt.isoformat()
        current_event["end_dt"] = photo_dt
        current_event["photo_count"] += 1
        current_event["size_bytes"] += photo.get("size_bytes") or 0
        current_event["photos"].append(photo.get("file_path", ""))

        # Update location if not set
        if not current_event["city"] and city:
            current_event["city"] = city
        if not current_event["country"] and country:
            current_event["country"] = country

    # Finalize last event
    if current_event:
        _finalize_event(current_event)
        events.append(current_event)

    return events


def _finalize_event(event: dict) -> None:
    """Clean up event dict for output (remove internal fields)."""
    event.pop("start_dt", None)
    event.pop("end_dt", None)
    # Format size
    event["size_str"] = format_size(event.get("size_bytes", 0))
    # Generate event name
    city = event.get("city", "")
    start = event.get("start_date", "")[:10]
    end = event.get("end_date", "")[:10]
    if city and start == end:
        event["name"] = f"{city} ({start})"
    elif city:
        event["name"] = f"{city} ({start} → {end})"
    elif start == end:
        event["name"] = start
    else:
        event["name"] = f"{start} → {end}"


def write_events_to_db(index_path: str, events: list) -> int:
    """Write event_id back to DB for each photo. Returns photos updated."""
    conn = sqlite3.connect(index_path)

    try:
        conn.execute("ALTER TABLE photos ADD COLUMN event_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_event_id ON photos(event_id)")
    except sqlite3.OperationalError:
        pass

    updated = 0
    for event in events:
        eid = event["event_id"]
        for path in event.get("photos", []):
            conn.execute("UPDATE photos SET event_id = ? WHERE file_path = ?", (eid, path))
            updated += 1

    conn.commit()
    conn.close()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cluster photos into events by time and location")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index")
    parser.add_argument("--output", "-o", dest="output", required=True,
                        help="Output events report (.json or .csv)")
    parser.add_argument("--gap-hours", type=float, default=4.0,
                        help="Minimum gap between events in hours (default: 4)")
    parser.add_argument("--use-location", action="store_true",
                        help="Start new event when city changes")
    parser.add_argument("--split-days", action="store_true", default=True,
                        help="Events don't cross midnight (default: True)")
    parser.add_argument("--write-db", action="store_true",
                        help="Write event_id back to index DB")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    print("📊 Clustering photos into events...")
    photos = load_photos_sorted(os.path.abspath(args.index))
    print(f"  Loaded {len(photos)} photos")

    events = cluster_events(
        photos,
        gap_hours=args.gap_hours,
        use_location=args.use_location,
        split_days=args.split_days,
    )

    # Write report
    output_path = os.path.abspath(args.output)
    ext = output_path.rsplit(".", 1)[-1].lower() if "." in output_path else "json"

    if ext == "json":
        # Don't include full photo paths in JSON (too verbose), just counts
        report_events = []
        for e in events:
            report = dict(e)
            report["photo_paths"] = report.pop("photos", [])
            report_events.append(report)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"total_events": len(events), "events": report_events}, f, indent=2, ensure_ascii=False)
    else:
        # CSV: one row per event
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["event_id", "name", "start_date", "end_date", "city", "country",
                          "photo_count", "size_bytes", "size_str"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for e in events:
                row = {k: e.get(k, "") for k in fieldnames}
                writer.writerow(row)

    # Write to DB
    if args.write_db:
        updated = write_events_to_db(os.path.abspath(args.index), events)
        print(f"  Updated {updated} photos with event_id in DB")

    print(f"\n{'=' * 50}")
    print(f"Event Clustering Report")
    print(f"  Total photos:   {len(photos)}")
    print(f"  Events found:   {len(events)}")
    if events:
        sizes = [e["photo_count"] for e in events]
        print(f"  Photos/event:   {min(sizes)}-{max(sizes)} (avg {sum(sizes)/len(sizes):.1f})")
    print(f"  Report saved:   {output_path}")


if __name__ == "__main__":
    main()
