#!/usr/bin/env python3
"""Scan a folder of photos and videos and build a metadata index.

This script walks a directory tree and collects metadata for image and video
files.  The output is stored in a SQLite database (preferred) or CSV.

Metadata collected:

* file_path – absolute path to the file
* filename – base name of the file
* extension – lower‑case file extension (without dot)
* size_bytes – file size in bytes
* sha256 – SHA‑256 digest of the file contents
* exif_datetime – original capture date from EXIF (if available)
* file_mtime – last modified timestamp (ISO format)
* width/height – dimensions for images (empty for videos)
* phash – perceptual hash for images (empty for videos or errors)
* media_type – "image" or "video"
* category – auto-detected: "photo", "screenshot", "wechat", "burst", "video"
* gps_latitude / gps_longitude – GPS coordinates from EXIF (if available)
* camera_make / camera_model – camera info from EXIF (if available)
* has_exif – whether the file contains EXIF metadata (bool)
* folder_tag – top-level subfolder name under scan root (for priority rules)
* aspect_ratio – width/height ratio (3 decimal places, for scaled duplicate detection)
* subsec_time – sub-second timestamp from EXIF SubSecTimeOriginal (for burst grouping)
* format_family – format group: "jpeg", "heic", "png", "tiff", "raw", "webp", "other"
  (for cross-format duplicate detection — HEIC vs JPEG of the same photo)

The script intentionally does not modify any files; it only reads metadata.
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Shared metadata helpers + optional-dependency flags (single source of truth)
from photo_metadata import (
    PILLOW_AVAILABLE, PIEXIF_AVAILABLE, IMAGEHASH_AVAILABLE, HEIC_SUPPORT,
    compute_sha256, get_exif_datetime, get_gps_coords, get_camera_info,
    has_exif_data, compute_phash, get_image_size, get_subsec_time,
    compute_aspect_ratio,
)
from constants import IMAGE_EXTS, VIDEO_EXTS, RAW_EXTS, HEIC_EXTS, get_format_family
from reverse_geocode import reverse_geocode, init_cache as geo_init_cache, flush_cache as geo_flush_cache

# Skip patterns for directories
SKIP_DIR_SUFFIXES = {
    ".photoslibrary", ".photolibrary",
    "Original_Backup_勿动", "99_Original_Backup",
    ".trashes", ".Trashes", ".Spotlight-V100",
    "__pycache__", ".git", ".svn",
    "node_modules",
}

# Screenshot detection patterns (multilingual)
# NOTE: "IMG_" is NOT listed here — iOS camera photos also use IMG_ prefix (JPG).
# iOS screenshots are IMG_*.PNG (uppercase), handled separately in detect_category().
SCREENSHOT_PATTERNS = [
    # English
    "screenshot", "screen shot",
    # Chinese (Simplified & Traditional)
    "截图", "截屏", "螢幕截圖", "截圖",
    # Japanese
    "スクリーンショット",
    # Korean
    "스크린샷",
    # Russian
    "скриншот",
    # French
    "capture d", "copie d",
    # German
    "bildschirmfoto", "bildschirmaufnahme",
    # Spanish
    "captura de pantalla",
    # Italian
    "schermata",
    # Portuguese
    "captura de tela",
    # Dutch
    "schermafbeelding",
    # Thai
    "ภาพหน้าจอ",
    # Vietnamese
    "chụp màn hình",
    # Indonesian
    "tangkapan layar",
]

# iOS screenshot: IMG_ followed by digits, saved as PNG (not JPG).
# Camera photos are also IMG_ but always JPG.
IOS_SCREENSHOT_RE = __import__("re").compile(r"^IMG_\d+\.PNG$", __import__("re").IGNORECASE)

# WeChat / messaging app image patterns (multilingual)
WECHAT_PATTERNS = [
    "mmexport", "wx_camera_", "wx_",
    "microMsg", "WeiXin",
    "微信", "wechat",
    # Korean KakaoTalk
    "KakaoTalk",
    # Japanese LINE
    "LINE_",
]

# Burst/HDR indicators in filenames (multilingual)
BURST_PATTERNS = [
    "_HDR", "_burst", "_Burst",
    "HDR_", "burst_",
    "连拍", "連拍",
    # Korean
    "버스트", "연속",
    # Japanese
    "連写", "バースト",
]


def detect_category(name: str, ext: str) -> str:
    """Auto-detect photo category based on filename and extension."""
    name_lower = name.lower()

    # Burst/HDR detection (check BEFORE screenshot — IMG_0010_HDR.jpg is burst, not screenshot)
    for pattern in BURST_PATTERNS:
        if pattern.lower() in name_lower:
            return "burst"

    # Screenshot detection
    # 1. iOS screenshot pattern: IMG_0001.PNG (not .JPG — those are camera photos)
    if IOS_SCREENSHOT_RE.match(name):
        return "screenshot"
    # 2. General screenshot keywords
    for pattern in SCREENSHOT_PATTERNS:
        if pattern.lower() in name_lower:
            return "screenshot"

    # WeChat image detection
    for pattern in WECHAT_PATTERNS:
        if pattern.lower() in name_lower:
            return "wechat"

    # RAW photo
    if ext in RAW_EXTS:
        return "photo"

    # Video
    if ext in VIDEO_EXTS:
        return "video"

    # Default
    return "photo"


def get_folder_tag(full_path: str, scan_root: str) -> str:
    """Get the top-level subfolder name under scan root (for priority rules)."""
    try:
        rel = os.path.relpath(full_path, scan_root)
        parts = rel.split(os.sep)
        if len(parts) > 1:
            return parts[0]
    except Exception:
        pass
    return ""


def _compute_entry(full_path, name, ext, stat, input_dir, scan_time, geocode=True):
    """Compute metadata dict for a single file.

    Returns a dict ready for INSERT OR REPLACE into the photos table.
    """
    size_bytes = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
    category = detect_category(name, ext)
    folder_tag = get_folder_tag(full_path, input_dir)

    # Initialize fields common to images and videos
    exif_dt = ""
    width = ""
    height = ""
    phash = ""
    gps_lat = ""
    gps_lon = ""
    camera_make = ""
    camera_model = ""
    has_exif_val = 0
    subsec_time = ""
    aspect_ratio = ""
    format_family = get_format_family(ext)
    place_city = ""
    place_region = ""
    place_country = ""
    place_country_code = ""

    if ext in IMAGE_EXTS:
        media_type = "image"
        exif_dt = get_exif_datetime(full_path)
        subsec_time = get_subsec_time(full_path)
        width, height = get_image_size(full_path)
        phash = compute_phash(full_path)
        aspect_ratio = compute_aspect_ratio(width, height)
        gps_lat, gps_lon = get_gps_coords(full_path)
        camera_make, camera_model = get_camera_info(full_path)
        has_exif_val = 1 if has_exif_data(full_path) else 0
        # Reverse geocode GPS → place name
        if geocode and gps_lat and gps_lon:
            place = reverse_geocode(gps_lat, gps_lon)
            place_city = place.get("place_city", "")
            place_region = place.get("place_region", "")
            place_country = place.get("place_country", "")
            place_country_code = place.get("place_country_code", "")
    else:
        media_type = "video"

    sha256 = compute_sha256(full_path)

    return {
        "file_path": full_path,
        "filename": name,
        "extension": ext,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "exif_datetime": exif_dt,
        "file_mtime": mtime,
        "width": width,
        "height": height,
        "phash": phash,
        "media_type": media_type,
        "category": category,
        "gps_latitude": gps_lat,
        "gps_longitude": gps_lon,
        "camera_make": camera_make,
        "camera_model": camera_model,
        "has_exif": has_exif_val,
        "folder_tag": folder_tag,
        "scan_root": input_dir,
        "scanned_at": scan_time,
        "aspect_ratio": aspect_ratio,
        "subsec_time": subsec_time,
        "format_family": format_family,
        "place_city": place_city,
        "place_region": place_region,
        "place_country": place_country,
        "place_country_code": place_country_code,
    }


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database with the photos table."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            file_path TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            exif_datetime TEXT DEFAULT '',
            file_mtime TEXT DEFAULT '',
            width TEXT DEFAULT '',
            height TEXT DEFAULT '',
            phash TEXT DEFAULT '',
            media_type TEXT NOT NULL DEFAULT 'image',
            category TEXT NOT NULL DEFAULT 'photo',
            gps_latitude TEXT DEFAULT '',
            gps_longitude TEXT DEFAULT '',
            camera_make TEXT DEFAULT '',
            camera_model TEXT DEFAULT '',
            has_exif INTEGER DEFAULT 0,
            folder_tag TEXT DEFAULT '',
            scan_root TEXT DEFAULT '',
            scanned_at TEXT DEFAULT ''
        )
    """)
    # Migrate: add new columns if they don't exist (backward compatible)
    new_columns = [
        ("aspect_ratio", "TEXT DEFAULT ''"),
        ("subsec_time", "TEXT DEFAULT ''"),
        ("format_family", "TEXT DEFAULT ''"),
        ("place_city", "TEXT DEFAULT ''"),
        ("place_region", "TEXT DEFAULT ''"),
        ("place_country", "TEXT DEFAULT ''"),
        ("place_country_code", "TEXT DEFAULT ''"),
    ]
    for col_name, col_type in new_columns:
        try:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    # Indexes for fast lookups
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sha256 ON photos(sha256)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phash ON photos(phash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON photos(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exif_datetime ON photos(exif_datetime)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_folder_tag ON photos(folder_tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_camera_model ON photos(camera_model)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aspect_ratio ON photos(aspect_ratio)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_format_family ON photos(format_family)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_place_city ON photos(place_city)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_place_country ON photos(place_country)")
    conn.commit()
    return conn


def _insert_entry(conn, entry):
    """Insert a single entry into the photos table."""
    cols = ", ".join(entry.keys())
    placeholders = ", ".join("?" for _ in entry)
    conn.execute(f"INSERT OR REPLACE INTO photos ({cols}) VALUES ({placeholders})",
                 list(entry.values()))


def scan_directory(input_dir: str, output_path: str, use_db: bool = True,
                    geocode: bool = True, parallel: int = 1,
                    incremental: bool = False) -> None:
    """Walk through input_dir and write metadata to SQLite DB or CSV.

    For SQLite mode, entries are written and committed one-by-one (serial)
    or in batches after parallel computation, so that a crash at any point
    never loses already-computed data.  Re-running the scan safely picks
    up where it left off (INSERT OR REPLACE).

    If incremental=True, only process files that are new or modified since
    the last scan (compared by file_path + size_bytes + file_mtime).
    """
    input_dir = os.path.abspath(input_dir)

    # Initialize geocode cache if enabled
    if geocode:
        cache_dir = os.path.dirname(os.path.abspath(output_path))
        geo_init_cache(cache_dir)
    scan_time = datetime.now().isoformat()
    categories = {}
    heic_count = 0

    # Phase 1: Collect file list (fast)
    file_list = []
    for root, dirs, files in os.walk(input_dir):
        # Skip Photos libraries, backup dirs, and system dirs
        dirs[:] = [d for d in dirs
                    if not any(d.endswith(s) or d == s for s in SKIP_DIR_SUFFIXES)]

        for name in files:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                continue
            file_list.append((root, name, ext))

    total_files = len(file_list)
    if total_files == 0:
        print("No photo/video files found.")
        return

    # --- Incremental scan: load existing index for change detection ---
    existing_index = {}  # file_path → (size_bytes, file_mtime)
    if incremental and use_db and os.path.exists(output_path):
        try:
            old_conn = sqlite3.connect(output_path)
            old_conn.row_factory = sqlite3.Row
            for row in old_conn.execute(
                "SELECT file_path, size_bytes, file_mtime FROM photos WHERE scan_root = ?",
                (input_dir,)
            ):
                existing_index[row["file_path"]] = (
                    row["size_bytes"] or 0,
                    row["file_mtime"] or "",
                )
            old_conn.close()
        except Exception:
            existing_index = {}

    skipped_unchanged = 0

    if use_db:
        # --- SQLite streaming mode ---
        conn = init_db(output_path)
        if not incremental:
            # Full scan: delete previous scan results for this root first
            conn.execute("DELETE FROM photos WHERE scan_root = ?", (input_dir,))
            conn.commit()

        # Filter valid files (stat check) before parallel processing
        valid_files = []
        for root, name, ext in file_list:
            full_path = os.path.join(root, name)
            try:
                lstat = os.lstat(full_path)
                if os.path.islink(full_path):
                    continue
                stat = os.stat(full_path)
                if stat.st_size == 0:
                    continue
                # Incremental: skip unchanged files
                if incremental and full_path in existing_index:
                    old_size, old_mtime = existing_index[full_path]
                    cur_mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    if stat.st_size == old_size and cur_mtime == old_mtime:
                        skipped_unchanged += 1
                        continue
                valid_files.append((full_path, name, ext, stat))
            except OSError:
                continue

        if parallel <= 1:
            # Sequential mode — commit each entry for zero data loss
            last_pct = -1
            for idx, (full_path, name, ext, stat) in enumerate(valid_files):
                pct = idx * 100 // len(valid_files)
                if pct >= last_pct + 5 or idx == 0:
                    print(f"  Scanning... {idx}/{len(valid_files)} ({pct}%)")
                    last_pct = pct

                entry = _compute_entry(full_path, name, ext, stat, input_dir, scan_time, geocode=geocode)
                _insert_entry(conn, entry)
                conn.commit()  # Commit every entry — zero data loss on crash

                cat = entry["category"]
                categories[cat] = categories.get(cat, 0) + 1
                if entry["extension"] in HEIC_EXTS:
                    heic_count += 1
        else:
            # Parallel mode — compute entries in threads, batch-write
            print(f"  Using {parallel} parallel workers...")
            last_pct = -1
            done_count = 0
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                future_to_file = {
                    executor.submit(_compute_entry, fp, name, ext, stat, input_dir, scan_time, geocode=geocode): (fp, name, ext)
                    for fp, name, ext, stat in valid_files
                }
                for future in as_completed(future_to_file):
                    done_count += 1
                    pct = done_count * 100 // len(valid_files)
                    if pct >= last_pct + 5 or done_count == 1:
                        print(f"  Scanning... {done_count}/{len(valid_files)} ({pct}%)")
                        last_pct = pct

                    try:
                        entry = future.result()
                        _insert_entry(conn, entry)
                        # Batch commit every 50 entries (balance speed vs. crash safety)
                        if done_count % 50 == 0:
                            conn.commit()

                        cat = entry["category"]
                        categories[cat] = categories.get(cat, 0) + 1
                        if entry["extension"] in HEIC_EXTS:
                            heic_count += 1
                    except Exception:
                        pass

            conn.commit()  # Final commit

        conn.close()

        # Stats
        total = sum(categories.values())
        print(f"Index written to SQLite: {output_path}")
        if incremental and skipped_unchanged > 0:
            print(f"  Incremental: {skipped_unchanged} unchanged, {total} new/modified")
        print(f"  Total: {total} files")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}")
        if not HEIC_SUPPORT and heic_count > 0:
            print(f"  ⚠️  {heic_count} HEIC/HEIF files found — install pillow-heif for full support:")
            print(f"      pip install pillow-heif")
    else:
        # --- CSV mode ---
        entries = []

        if parallel <= 1:
            last_pct = -1
            for idx, (root, name, ext) in enumerate(file_list):
                pct = idx * 100 // total_files
                if pct >= last_pct + 5 or idx == 0:
                    print(f"  Scanning... {idx}/{total_files} ({pct}%)")
                    last_pct = pct

                full_path = os.path.join(root, name)
                try:
                    lstat = os.lstat(full_path)
                    if os.path.islink(full_path):
                        continue
                    stat = os.stat(full_path)
                    if stat.st_size == 0:
                        continue
                except OSError:
                    continue

                entry = _compute_entry(full_path, name, ext, stat, input_dir, scan_time, geocode=geocode)
                entries.append(entry)
        else:
            # Parallel CSV mode
            valid_files = []
            for root, name, ext in file_list:
                full_path = os.path.join(root, name)
                try:
                    lstat = os.lstat(full_path)
                    if os.path.islink(full_path):
                        continue
                    stat = os.stat(full_path)
                    if stat.st_size == 0:
                        continue
                    valid_files.append((full_path, name, ext, stat))
                except OSError:
                    continue

            print(f"  Using {parallel} parallel workers...")
            last_pct = -1
            done_count = 0
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                future_to_file = {
                    executor.submit(_compute_entry, fp, name, ext, stat, input_dir, scan_time, geocode=geocode): (fp, name, ext)
                    for fp, name, ext, stat in valid_files
                }
                for future in as_completed(future_to_file):
                    done_count += 1
                    pct = done_count * 100 // len(valid_files)
                    if pct >= last_pct + 5 or done_count == 1:
                        print(f"  Scanning... {done_count}/{len(valid_files)} ({pct}%)")
                        last_pct = pct
                    try:
                        entries.append(future.result())
                    except Exception:
                        pass

        fieldnames = list(entries[0].keys()) if entries else []
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in entries:
                writer.writerow(row)
        print(f"Index written to CSV: {output_path} ({len(entries)} files)")

    # Flush geocode cache to disk
    if geocode:
        geo_flush_cache()


def main() -> None:
    # Check optional dependencies and warn
    missing = []
    if not PILLOW_AVAILABLE:
        missing.append("Pillow (pip install Pillow)")
    if not PIEXIF_AVAILABLE:
        missing.append("piexif (pip install piexif)")
    if not IMAGEHASH_AVAILABLE:
        missing.append("imagehash (pip install imagehash)")
    if missing:
        print("⚠️  Optional dependencies not installed — some features will be unavailable:", file=sys.stderr)
        for m in missing:
            print(f"     - {m}", file=sys.stderr)
        print("     phash, EXIF, dimensions, and image size will be empty.", file=sys.stderr)
        print("     Install with: pip install Pillow piexif imagehash", file=sys.stderr)
        print(file=sys.stderr)

    parser = argparse.ArgumentParser(
        description="Scan photos/videos and build metadata index (SQLite or CSV)")
    parser.add_argument("--source", "--input", "-i", dest="source", required=True,
                        help="Directory to scan (alias: --input)")
    parser.add_argument("--output", "-o", dest="output", required=True,
                        help="Output index path (.db for SQLite, .csv for CSV)")
    parser.add_argument("--format", choices=["auto", "db", "csv"], default="auto",
                        help="Output format (default: auto-detect from file extension)")
    parser.add_argument("--geocode", action="store_true", default=True,
                        help="Reverse-geocode GPS coordinates to place names (default: on)")
    parser.add_argument("--no-geocode", action="store_false", dest="geocode",
                        help="Skip reverse geocoding (faster scan)")
    parser.add_argument("--parallel", "-p", type=int, default=1,
                        help="Number of parallel workers (default: 1, try 4 for speed)")
    parser.add_argument("--incremental", action="store_true",
                        help="Only scan new or modified files (skip unchanged, DB mode only)")
    args = parser.parse_args()

    input_dir = os.path.abspath(args.source)
    output_path = os.path.abspath(args.output)

    if not os.path.isdir(input_dir):
        print(f"Error: {input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Auto-detect format
    fmt = args.format
    if fmt == "auto":
        use_db = output_path.endswith(".db")
    elif fmt == "db":
        use_db = True
    else:
        use_db = False

    scan_directory(input_dir, output_path, use_db=use_db, geocode=args.geocode,
                   parallel=args.parallel, incremental=args.incremental)


if __name__ == "__main__":
    main()
