#!/usr/bin/env python3
"""Fix missing or incorrect photo dates by inferring from filename, neighbors, or file mtime.

Strategies (in order of priority):
  1. Extract date from filename pattern (15+ common patterns)
  2. Infer from neighbor photos in same folder (same folder, within X minutes)
  3. Fall back to file modification time

Writes corrected date to EXIF DateTimeOriginal and updates the index DB.
Supports --dry-run (preview only), --write-exif (modify files), --report.

Usage:
  python fix_dates.py --index photo_index.db [--dry-run] [--write-exif] [--report fixed.csv]
  python fix_dates.py --index photo_index.db --strategy filename-only [--dry-run]
  python fix_dates.py --index photo_index.db --strategy neighbors --neighbor-gap 30
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Filename date extraction patterns
# ---------------------------------------------------------------------------

# Each pattern: (regex, date_format_or_parser)
# Parser returns datetime or None
FILENAME_PATTERNS = [
    # IMG_20250615_094235.HEIC — iOS camera
    (r"(?:IMG|img)_(\d{8})_(\d{6})", lambda m: _parse_ymd_hms(m.group(1), m.group(2))),
    # IMG_20250615_094235_123.HEIC — iOS camera with subsec
    (r"(?:IMG|img)_(\d{8})_(\d{6})_\d+", lambda m: _parse_ymd_hms(m.group(1), m.group(2))),
    # Screenshot_2025-06-15-09-42-35-934.png — Android screenshot
    (r"Screenshot[_\s](\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})",
     lambda m: datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)))),
    # Screenshot 2025-06-15 at 09.42.35.png — macOS screenshot
    (r"Screenshot\s+(\d{4})-(\d{2})-(\d{2})\s+at\s+(\d{2})\.(\d{2})\.(\d{2})",
     lambda m: datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)))),
    # Screenshot 2025-06-15 at 9.42.35 AM.png — macOS screenshot with AM/PM
    (r"Screenshot\s+(\d{4})-(\d{2})-(\d{2})\s+at\s+(\d{1,2})\.(\d{2})\.(\d{2})\s*(AM|PM)",
     lambda m: _parse_12h_datetime(m)),
    # WX20250615-094235.png — WeChat
    (r"WX(\d{8})-(\d{6})", lambda m: _parse_ymd_hms(m.group(1), m.group(2))),
    # mmexport1686812556085.jpg — WeChat (timestamp)
    (r"mmexport(\d{13}|\d{10})", lambda m: _parse_timestamp(m.group(1))),
    # wx_camera_1686812556085.jpg — WeChat camera (timestamp)
    (r"wx_camera_(\d{13}|\d{10})", lambda m: _parse_timestamp(m.group(1))),
    # microMsg_1686812556085.jpg — WeChat
    (r"microMsg[_\s](\d{13}|\d{10})", lambda m: _parse_timestamp(m.group(1))),
    # VID_20250615_094235.mp4 — Android video
    (r"(?:VID|vid)_(\d{8})_(\d{6})", lambda m: _parse_ymd_hms(m.group(1), m.group(2))),
    # 20250615_094235.jpg — generic YYYYMMDD_HHMMSS
    (r"(\d{8})_(\d{6})", lambda m: _parse_ymd_hms(m.group(1), m.group(2))),
    # 2025-06-15 09.42.35.jpg — date with dots
    (r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2})\.(\d{2})\.(\d{2})",
     lambda m: datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)))),
    # 20250615094235.jpg — compact YYYYMMDDHHMMSS
    (r"(\d{14})", lambda m: datetime.strptime(m.group(1), "%Y%m%d%H%M%S")),
    # 1371485412561.jpg — Unix timestamp (13-digit ms or 10-digit s)
    (r"^(\d{13}|\d{10})\.", lambda m: _parse_timestamp(m.group(1))),
    # FB_IMG_1686812556085.jpg — Facebook
    (r"FB_IMG[_\s](\d{13}|\d{10})", lambda m: _parse_timestamp(m.group(1))),
    # Signal-2025-06-15-09-42-35.jpg — Signal
    (r"Signal-(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})",
     lambda m: datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)))),
    # LINE_1686812556085.jpg — LINE
    (r"LINE[_\s](\d{13}|\d{10})", lambda m: _parse_timestamp(m.group(1))),
    # KakaoTalk_20250615_094235.jpg — KakaoTalk
    (r"KakaoTalk[_\s](\d{8})[_\s](\d{6})", lambda m: _parse_ymd_hms(m.group(1), m.group(2))),
]


def _parse_ymd_hms(date_str: str, time_str: str) -> datetime:
    """Parse YYYYMMDD and HHMMSS into datetime."""
    return datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S")


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse Unix timestamp (10-digit seconds or 13-digit milliseconds)."""
    ts = int(ts_str)
    if len(ts_str) == 13:
        ts = ts / 1000
    return datetime.fromtimestamp(ts)


def _parse_12h_datetime(m) -> datetime:
    """Parse 12-hour format datetime from regex match."""
    h = int(m.group(4))
    if m.group(6).upper() == "PM" and h != 12:
        h += 12
    elif m.group(6).upper() == "AM" and h == 12:
        h = 0
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    h, int(m.group(5)), int(m.group(6) if len(m.group(6)) == 2 else 0))


def extract_date_from_filename(filename: str) -> datetime | None:
    """Try to extract a date from a filename using known patterns.

    Returns datetime if found, None otherwise.
    Validates that the date is between 2000-01-01 and 2035-01-01.
    """
    for pattern, parser in FILENAME_PATTERNS:
        m = re.search(pattern, filename, re.IGNORECASE)
        if m:
            try:
                dt = parser(m)
                if dt and datetime(2000, 1, 1) <= dt <= datetime(2035, 1, 1):
                    return dt
            except (ValueError, OSError, OverflowError):
                continue
    return None


# ---------------------------------------------------------------------------
# Neighbor date inference
# ---------------------------------------------------------------------------

def infer_date_from_neighbors(file_path: str, folder_files: list,
                              gap_minutes: int = 30) -> datetime | None:
    """Infer date from neighbor photos in the same folder.

    Finds the closest photo by filename sort order within gap_minutes
    of its date. Useful for burst-mode or sequential shots.

    The gap_minutes parameter controls the maximum allowed time span
    between the two nearest valid neighbors. If the two closest neighbors
    with valid dates are more than gap_minutes apart, the inference is
    considered unreliable and None is returned.
    """
    # Sort files by name for ordering
    sorted_files = sorted(folder_files, key=lambda x: x[0])
    my_idx = None
    for i, (fp, dt, _) in enumerate(sorted_files):
        if fp == file_path:
            my_idx = i
            break

    if my_idx is None:
        return None

    # Collect valid neighbors in order of distance (by index)
    # A valid neighbor has a date and is not itself inferred from a neighbor
    ordered_neighbors = []
    for offset in range(1, len(sorted_files)):
        for idx in [my_idx - offset, my_idx + offset]:
            if 0 <= idx < len(sorted_files):
                _, dt, source = sorted_files[idx]
                if dt and source not in ("neighbor", "missing"):
                    ordered_neighbors.append((abs(idx - my_idx), dt))

    if not ordered_neighbors:
        return None

    # Use the closest neighbor's date
    ordered_neighbors.sort(key=lambda x: x[0])
    closest_date = ordered_neighbors[0][1]

    # Validate with gap_minutes: if we have a second neighbor,
    # check that the time span between neighbors is reasonable
    if len(ordered_neighbors) >= 2:
        second_date = ordered_neighbors[1][1]
        time_span = abs((closest_date - second_date).total_seconds()) / 60
        if time_span > gap_minutes:
            return None  # Neighbors disagree too much — unreliable

    return closest_date


# ---------------------------------------------------------------------------
# EXIF date writing
# ---------------------------------------------------------------------------

def write_exif_date(file_path: str, dt: datetime, dry_run: bool = False) -> bool:
    """Write date to EXIF DateTimeOriginal and DateTimeDigitized.

    Returns True if successful, False otherwise.
    """
    if dry_run:
        return True

    ext = Path(file_path).suffix.lower()

    # Try piexif for JPEG/TIFF
    if ext in (".jpg", ".jpeg", ".tiff", ".tif"):
        try:
            import piexif
            date_str = dt.strftime("%Y:%m:%d %H:%M:%S")

            # Load existing EXIF or create new
            try:
                exif_dict = piexif.load(file_path)
            except Exception:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

            exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = date_str.encode()
            exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = date_str.encode()

            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, file_path)
            return True
        except Exception:
            pass

    # Try exiftool for HEIC/RAW and fallback
    try:
        import subprocess
        date_str = dt.strftime("%Y:%m:%d %H:%M:%S")
        result = subprocess.run(
            ["exiftool", "-overwrite_original",
             f"-DateTimeOriginal={date_str}",
             f"-CreateDate={date_str}",
             f"-ModifyDate={date_str}",
             file_path],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

MIN_VALID_YEAR = 2000
MAX_VALID_YEAR = 2035


def is_date_valid(date_str: str) -> bool:
    """Check if an EXIF date string is valid and in reasonable range.

    Supports formats: YYYY:MM:DD HH:MM:SS, YYYY-MM-DD HH:MM:SS,
    YYYY-MM-DDTHH:MM:SS (ISO with T separator, with optional microseconds).
    """
    if not date_str or len(date_str) < 10:
        return False

    # Normalize: strip microseconds and replace T with space
    normalized = date_str[:19].replace("T", " ")

    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(normalized, fmt)
            return MIN_VALID_YEAR <= dt.year <= MAX_VALID_YEAR
        except ValueError:
            continue
    return False


def fix_dates(index_path: str, strategy: str = "all", neighbor_gap: int = 30,
              dry_run: bool = False, write_exif: bool = False,
              report_path: str = "") -> dict:
    """Fix dates for photos with missing or invalid EXIF dates.

    Returns dict with stats: {total, fixed, by_source, errors}.
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Get all files
    rows = conn.execute(
        "SELECT file_path, filename, extension, exif_datetime, file_mtime FROM photos"
    ).fetchall()

    # Separate files with valid vs invalid dates
    needs_fix = []
    has_date = []  # Files with valid dates (for neighbor inference)

    for row in rows:
        fp = row["file_path"]
        fn = row["filename"]
        ext = row["extension"] or ""
        exif_dt = row["exif_datetime"] or ""
        file_mtime = row["file_mtime"] or ""

        if is_date_valid(exif_dt):
            # Has valid date — use as neighbor reference
            normalized = exif_dt[:19].replace("T", " ")
            dt = None
            for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(normalized, fmt)
                    break
                except ValueError:
                    continue
            if dt:
                has_date.append((fp, dt, "exif"))
        else:
            needs_fix.append({
                "file_path": fp,
                "filename": fn,
                "extension": ext,
                "exif_datetime": exif_dt,
                "file_mtime": file_mtime,
            })

    print(f"  📅 {len(needs_fix)} photos need date fix, {len(has_date)} have valid dates")

    # Group files by folder for neighbor inference
    folder_map = defaultdict(list)
    for fp, dt, source in has_date:
        folder = str(Path(fp).parent)
        folder_map[folder].append((fp, dt, source))

    # Also add files needing fix to folder map (with None date)
    # so that infer_date_from_neighbors() can locate them in the sorted list
    for item in needs_fix:
        folder = str(Path(item["file_path"]).parent)
        folder_map[folder].append((item["file_path"], None, "missing"))

    # Fix dates
    stats = {"total": len(needs_fix), "fixed": 0, "by_source": defaultdict(int), "errors": 0}
    fixes = []

    for item in needs_fix:
        fp = item["file_path"]
        fn = item["filename"]
        ext = item["extension"]
        file_mtime = item["file_mtime"]

        new_date = None
        source = ""

        # Strategy 1: Filename extraction
        if strategy in ("all", "filename-only"):
            new_date = extract_date_from_filename(fn)
            if new_date:
                source = "filename"

        # Strategy 2: Neighbor inference
        if not new_date and strategy in ("all", "neighbors"):
            folder = str(Path(fp).parent)
            neighbor_date = infer_date_from_neighbors(fp, folder_map.get(folder, []),
                                                      gap_minutes=neighbor_gap)
            if neighbor_date:
                new_date = neighbor_date
                source = "neighbor"

        # Strategy 3: File mtime fallback
        if not new_date and strategy in ("all", "mtime") and file_mtime:
            normalized = file_mtime[:19].replace("T", " ")
            for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    new_date = datetime.strptime(normalized, fmt)
                    source = "file_mtime"
                    break
                except ValueError:
                    continue

        if new_date:
            new_date_str = new_date.strftime("%Y:%m:%d %H:%M:%S")
            fixes.append({
                "file_path": fp,
                "old_date": item["exif_datetime"] or "(none)",
                "new_date": new_date_str,
                "source": source,
            })
            stats["fixed"] += 1
            stats["by_source"][source] += 1

            # Write EXIF if requested
            if write_exif and not dry_run:
                ok = write_exif_date(fp, new_date, dry_run=False)
                if not ok:
                    stats["errors"] += 1

            # Update DB
            if not dry_run:
                conn.execute(
                    "UPDATE photos SET exif_datetime=? WHERE file_path=?",
                    (new_date_str, fp),
                )

    conn.commit()
    conn.close()

    # Write report
    if report_path and fixes:
        with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["file_path", "old_date", "new_date", "source"])
            writer.writeheader()
            writer.writerows(fixes)
        print(f"  Report → {report_path}")

    return dict(stats)


def main():
    parser = argparse.ArgumentParser(
        description="Fix missing or incorrect photo dates by inferring from filename, neighbors, or file mtime",
    )
    parser.add_argument("--index", "-i", required=True, help="Path to SQLite index DB")
    parser.add_argument("--strategy", "-s",
                        choices=["all", "filename-only", "neighbors", "mtime"],
                        default="all",
                        help="Date inference strategy (default: all)")
    parser.add_argument("--neighbor-gap", type=int, default=30,
                        help="Maximum minutes gap for neighbor inference (default: 30)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without modifying files or DB")
    parser.add_argument("--write-exif", action="store_true",
                        help="Write corrected date to EXIF (implies modifying files)")
    parser.add_argument("--report", "-o", default="", help="Output CSV report of fixes")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index DB not found: {args.index}")
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"📅 Fixing photo dates [{mode}]...")
    print(f"  Strategy: {args.strategy}")

    start = time.time()
    stats = fix_dates(
        args.index,
        strategy=args.strategy,
        neighbor_gap=args.neighbor_gap,
        dry_run=args.dry_run,
        write_exif=args.write_exif,
        report_path=args.report,
    )
    elapsed = time.time() - start

    print(f"\n  ✅ Done in {elapsed:.1f}s")
    print(f"  Photos needing fix: {stats['total']}")
    print(f"  Fixed: {stats['fixed']}")
    if stats["by_source"]:
        print("  By source:")
        for source, count in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
            print(f"    {source}: {count}")
    if stats["errors"] > 0:
        print(f"  ⚠️  EXIF write errors: {stats['errors']}")


if __name__ == "__main__":
    main()
