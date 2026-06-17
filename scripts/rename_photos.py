#!/usr/bin/env python3
"""Smart photo renaming — rename photos based on EXIF metadata.

Renames photos using configurable templates with metadata tokens:
  {date}      → 2025-06-15
  {time}      → 14-30-25
  {camera}    → iPhone 15 Pro
  {city}      → 北京
  {country}   → 中国
  {seq}       → 001 (auto-incrementing sequence within same date/camera)
  {original}  → original filename without extension

Example outputs:
  2025-06-15_14-30_iPhone15Pro_001.jpg
  2025-06-15_北京_iPhone15Pro.jpg
  2025-06-15_001.jpg

Safety features:
  - Dry-run by default (preview only)
  - Never overwrites existing files (appends sequence number)
  - Preserves original extension
  - Creates undo record for batch rename

Usage:
    # Preview rename with default template
    python3 scripts/rename_photos.py --index photo_index.db --template "{date}_{camera}_{seq}"

    # Execute rename
    python3 scripts/rename_photos.py --index photo_index.db --template "{date}_{camera}_{seq}" --execute

    # Use location in filename
    python3 scripts/rename_photos.py --index photo_index.db --template "{date}_{city}_{seq}" --execute

    # Rename only screenshots
    python3 scripts/rename_photos.py --index photo_index.db --template "screenshot_{date}_{time}" \
        --execute --filter category=screenshot

    # Rename with custom date format
    python3 scripts/rename_photos.py --index photo_index.db --template "{date}_{seq}" \
        --date-format "%Y%m%d" --execute
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

from constants import IMAGE_EXTS


def sanitize_filename(name: str) -> str:
    """Remove/replace characters that are invalid in filenames."""
    # Replace common problematic chars
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    # Replace multiple spaces/underscores with single
    name = re.sub(r'[_\s]+', '_', name)
    # Strip leading/trailing dots and spaces
    name = name.strip('. ')
    # Limit length
    if len(name) > 200:
        name = name[:200]
    return name


def format_template(template: str, meta: dict, seq: int = 1,
                    date_format: str = "%Y-%m-%d") -> str:
    """Format a rename template with metadata values.

    Available tokens:
      {date}      → formatted date from date_format
      {time}      → HH-MM-SS
      {camera}    → camera model (or 'unknown')
      {city}      → place city (or '')
      {country}   → place country (or '')
      {seq}       → zero-padded sequence number (001, 002, ...)
      {original}  → original filename without extension
      {year}      → 4-digit year
      {month}     → 2-digit month
      {day}       → 2-digit day
    """
    dt_str = meta.get("exif_datetime") or meta.get("file_mtime") or ""
    dt = None
    if dt_str and len(dt_str) >= 19:
        try:
            dt = datetime.fromisoformat(dt_str[:19])
        except ValueError:
            pass

    # Build replacement dict
    replacements = {}

    if dt:
        replacements["date"] = dt.strftime(date_format)
        replacements["time"] = dt.strftime("%H-%M-%S")
        replacements["year"] = dt.strftime("%Y")
        replacements["month"] = dt.strftime("%m")
        replacements["day"] = dt.strftime("%d")
    else:
        replacements["date"] = "unknown-date"
        replacements["time"] = "unknown-time"
        replacements["year"] = "0000"
        replacements["month"] = "00"
        replacements["day"] = "00"

    # Camera
    camera = (meta.get("camera_model") or "").strip()
    if camera:
        camera = re.sub(r'\s+', '', camera)  # Remove spaces
    replacements["camera"] = camera or "unknown"

    # Location
    replacements["city"] = meta.get("place_city") or ""
    replacements["country"] = meta.get("place_country") or ""

    # Sequence
    replacements["seq"] = f"{seq:03d}"

    # Original filename
    orig = meta.get("filename") or ""
    if "." in orig:
        orig = orig.rsplit(".", 1)[0]
    replacements["original"] = orig

    # Apply template
    result = template
    for token, value in replacements.items():
        result = result.replace(f"{{{token}}}", value)

    return sanitize_filename(result)


def compute_rename_plan(index_path: str, template: str, date_format: str = "%Y-%m-%d",
                        filters: dict = None) -> list:
    """Compute rename plan for all photos matching filters.

    Returns list of {file_path, old_name, new_name, extension, directory}
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    select_fields = ["file_path", "filename", "extension", "exif_datetime", "file_mtime"]
    for col in ("camera_model", "place_city", "place_country", "category", "media_type"):
        if col in available_cols:
            select_fields.append(col)

    query = f"SELECT {', '.join(select_fields)} FROM photos WHERE media_type = 'image'"
    conditions = []

    # Apply filters
    if filters:
        if "category" in filters:
            conditions.append(f"category = '{filters['category']}'")

    if conditions:
        query += " AND " + " AND ".join(conditions)

    cursor = conn.execute(query)
    rows = [dict(row) for row in cursor]
    conn.close()

    # Group by directory + date + camera for sequence numbering
    seq_groups = defaultdict(int)

    # First pass: compute new names
    plan = []
    for row in rows:
        ext = row.get("extension") or ""
        directory = os.path.dirname(row["file_path"])

        # Build sequence key
        dt_str = row.get("exif_datetime") or row.get("file_mtime") or ""
        date_key = dt_str[:10] if dt_str else "unknown"
        camera_key = (row.get("camera_model") or "").strip()
        seq_key = f"{directory}|{date_key}|{camera_key}"

        seq_groups[seq_key] += 1
        seq = seq_groups[seq_key]

        new_name = format_template(template, row, seq, date_format)

        plan.append({
            "file_path": row["file_path"],
            "old_name": row.get("filename", ""),
            "new_name": f"{new_name}.{ext}",
            "extension": ext,
            "directory": directory,
        })

    # Handle name collisions (append _2, _3, etc.)
    name_counts = defaultdict(int)
    for item in plan:
        key = f"{item['directory']}|{item['new_name']}"
        name_counts[key] += 1

    # Second pass: resolve collisions
    seen = defaultdict(int)
    for item in plan:
        key = f"{item['directory']}|{item['new_name']}"
        if name_counts[key] > 1:
            seen[key] += 1
            base, ext = item["new_name"].rsplit(".", 1)
            item["new_name"] = f"{base}_{seen[key]}.{ext}"

    return plan


def execute_rename(plan: list, dry_run: bool = True) -> dict:
    """Execute the rename plan.

    Returns stats dict.
    """
    stats = {"renamed": 0, "skipped": 0, "errors": 0}
    undo_records = []

    for item in plan:
        old_path = item["file_path"]
        new_path = os.path.join(item["directory"], item["new_name"])

        if old_path == new_path:
            stats["skipped"] += 1
            continue

        if os.path.exists(new_path) and old_path != new_path:
            stats["skipped"] += 1
            continue

        if dry_run:
            stats["renamed"] += 1
            continue

        try:
            os.rename(old_path, new_path)
            undo_records.append({"old": old_path, "new": new_path})
            stats["renamed"] += 1
        except OSError:
            stats["errors"] += 1

    # Save undo record
    if not dry_run and undo_records:
        import tempfile
        undo_path = os.path.join(tempfile.gettempdir(), "snaptidy_rename_undo.json")
        with open(undo_path, "w") as f:
            json.dump(undo_records, f, indent=2)
        stats["undo_file"] = undo_path

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smart photo renaming — rename based on EXIF metadata")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index")
    parser.add_argument("--template", "-t", default="{date}_{camera}_{seq}",
                        help='Rename template (default: "{date}_{camera}_{seq}")')
    parser.add_argument("--date-format", default="%Y-%m-%d",
                        help="Date format string (default: %%Y-%%m-%%d)")
    parser.add_argument("--filter", action="append", default=[],
                        help="Filter: key=value (e.g., category=screenshot)")
    parser.add_argument("--execute", action="store_true",
                        help="Execute rename (default: dry-run preview)")
    parser.add_argument("--report", "-r", default="",
                        help="Save rename plan to CSV")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    # Parse filters
    filters = {}
    for f in args.filter:
        if "=" in f:
            k, v = f.split("=", 1)
            filters[k] = v

    # Compute plan
    plan = compute_rename_plan(
        os.path.abspath(args.index),
        template=args.template,
        date_format=args.date_format,
        filters=filters if filters else None,
    )

    # Show preview
    print(f"\nRename Plan ({len(plan)} files)")
    print(f"  Template: {args.template}")
    print(f"  Mode:     {'EXECUTE' if args.execute else 'DRY RUN'}")
    print()

    # Show first 20 examples
    for item in plan[:20]:
        print(f"  {item['old_name']}")
        print(f"    → {item['new_name']}")
    if len(plan) > 20:
        print(f"  ... and {len(plan) - 20} more")

    # Save report
    if args.report:
        fieldnames = ["file_path", "old_name", "new_name", "extension", "directory"]
        with open(os.path.abspath(args.report), "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(plan)

    # Execute
    stats = execute_rename(plan, dry_run=not args.execute)

    print(f"\n{'=' * 50}")
    print(f"Rename Report")
    print(f"  Total files:  {len(plan)}")
    print(f"  Renamed:      {stats['renamed']}")
    print(f"  Skipped:      {stats['skipped']}")
    if stats.get("errors"):
        print(f"  Errors:       {stats['errors']}")
    if not args.execute:
        print(f"  Mode: DRY RUN — no files were renamed")
        print(f"  Use --execute to actually rename")
    if stats.get("undo_file"):
        print(f"  Undo file: {stats['undo_file']}")


if __name__ == "__main__":
    main()
