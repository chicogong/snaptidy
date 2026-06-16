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
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime

try:
    from PIL import Image
except ImportError:
    print("Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)

try:
    import piexif
except ImportError:
    print("piexif is required. Install with: pip install piexif", file=sys.stderr)
    sys.exit(1)

try:
    import imagehash
except ImportError:
    print("imagehash is required. Install with: pip install imagehash", file=sys.stderr)
    sys.exit(1)

# Optional HEIC/HEIF support via pillow-heif
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False


IMAGE_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff", "heic", "heif",
    "webp", "dng", "cr2", "nef", "arw",  # RAW formats
}
VIDEO_EXTS = {
    "mov", "mp4", "m4v", "avi", "mkv", "3gp", "mpg", "mpeg",
    "hevc", "wmv", "flv",
}

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


def compute_sha256(path: str) -> str:
    """Compute the SHA‑256 hash of a file in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_exif_datetime(path: str) -> str:
    """Extract DateTimeOriginal from EXIF data if present.  Returns ISO string or ''."""
    try:
        exif_dict = piexif.load(path)
        dt = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if not dt:
            # Fallback to Image DateTime
            dt = exif_dict.get("0th", {}).get(piexif.ImageIFD.DateTime)
        if dt:
            if isinstance(dt, bytes):
                dt = dt.decode(errors="ignore")
            dt_str = dt.replace("\x00", "").strip()
            if len(dt_str) >= 19:
                try:
                    dt_obj = datetime.strptime(dt_str[:19], "%Y:%m:%d %H:%M:%S")
                    return dt_obj.isoformat()
                except Exception:
                    pass
    except Exception:
        return ""
    return ""


def get_gps_coords(path: str) -> tuple:
    """Extract GPS latitude/longitude from EXIF.  Returns (lat, lon) or ('', '')."""
    try:
        exif_dict = piexif.load(path)
        gps_ifd = exif_dict.get("GPS", {})
        if not gps_ifd:
            return "", ""

        def _convert_to_degrees(value):
            """Convert GPS coordinates (degrees, minutes, seconds) to decimal."""
            if not value or len(value) < 3:
                return None
            d = float(value[0][0]) / float(value[0][1]) if value[0][1] != 0 else 0
            m = float(value[1][0]) / float(value[1][1]) if value[1][1] != 0 else 0
            s = float(value[2][0]) / float(value[2][1]) if value[2][1] != 0 else 0
            return d + m / 60.0 + s / 3600.0

        lat_val = gps_ifd.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef)
        lon_val = gps_ifd.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef)

        lat = _convert_to_degrees(lat_val)
        lon = _convert_to_degrees(lon_val)

        if lat is not None and lon is not None:
            if isinstance(lat_ref, bytes):
                lat_ref = lat_ref.decode(errors="ignore")
            if isinstance(lon_ref, bytes):
                lon_ref = lon_ref.decode(errors="ignore")
            if lat_ref == "S":
                lat = -lat
            if lon_ref == "W":
                lon = -lon
            return round(lat, 6), round(lon, 6)
    except Exception:
        pass
    return "", ""


def get_camera_info(path: str) -> tuple:
    """Extract camera make/model from EXIF.  Returns (make, model) or ('', '')."""
    try:
        exif_dict = piexif.load(path)
        zeroth = exif_dict.get("0th", {})
        make = zeroth.get(piexif.ImageIFD.Make, "")
        model = zeroth.get(piexif.ImageIFD.Model, "")
        if isinstance(make, bytes):
            make = make.decode(errors="ignore").strip()
        if isinstance(model, bytes):
            model = model.decode(errors="ignore").strip()
        return make, model
    except Exception:
        return "", ""


def has_exif_data(path: str) -> bool:
    """Check if the file has meaningful EXIF data (beyond just file stats)."""
    try:
        exif_dict = piexif.load(path)
        # Check for any of: exposure, GPS, actual camera info
        has_exif_section = bool(exif_dict.get("Exif"))
        has_gps = bool(exif_dict.get("GPS"))
        zeroth = exif_dict.get("0th", {})
        has_camera = bool(zeroth.get(piexif.ImageIFD.Make)) or bool(zeroth.get(piexif.ImageIFD.Model))
        return has_exif_section or has_gps or has_camera
    except Exception:
        return False


def compute_phash(path: str) -> str:
    """Compute perceptual hash for an image.  Returns hex string or '' on error."""
    try:
        with Image.open(path) as img:
            ph = imagehash.average_hash(img.convert("RGB"))
            return str(ph)
    except Exception:
        return ""


def get_image_size(path: str) -> tuple:
    """Return (width, height) of an image or ('', '') on failure."""
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return "", ""


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
    if ext in ("dng", "cr2", "nef", "arw"):
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


def get_subsec_time(path: str) -> str:
    """Extract SubSecTimeOriginal from EXIF.  Returns string or ''."""
    try:
        exif_dict = piexif.load(path)
        subsec = exif_dict.get("Exif", {}).get(piexif.ExifIFD.SubSecTimeOriginal)
        if not subsec:
            # Fallback to SubSecTime (not "Original")
            subsec = exif_dict.get("Exif", {}).get(piexif.ExifIFD.SubSecTime)
        if subsec:
            if isinstance(subsec, bytes):
                subsec = subsec.decode(errors="ignore")
            return str(subsec).strip().rstrip("\x00")
    except Exception:
        pass
    return ""


def get_format_family(ext: str) -> str:
    """Group file extension into format family for cross-format dedup."""
    ext_lower = ext.lower()
    if ext_lower in ("jpg", "jpeg"):
        return "jpeg"
    elif ext_lower in ("heic", "heif"):
        return "heic"
    elif ext_lower == "png":
        return "png"
    elif ext_lower in ("tif", "tiff"):
        return "tiff"
    elif ext_lower in ("dng", "cr2", "nef", "arw"):
        return "raw"
    elif ext_lower == "webp":
        return "webp"
    else:
        return "other"


def compute_aspect_ratio(width, height) -> str:
    """Compute width/height ratio rounded to 3 decimal places."""
    try:
        w = int(width)
        h = int(height)
        if w > 0 and h > 0:
            return f"{w / h:.3f}"
    except (ValueError, TypeError):
        pass
    return ""


def _compute_entry(full_path, name, ext, stat, input_dir, scan_time):
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
    conn.commit()
    return conn


def _insert_entry(conn, entry):
    """Insert a single entry into the photos table."""
    cols = ", ".join(entry.keys())
    placeholders = ", ".join("?" for _ in entry)
    conn.execute(f"INSERT OR REPLACE INTO photos ({cols}) VALUES ({placeholders})",
                 list(entry.values()))


def scan_directory(input_dir: str, output_path: str, use_db: bool = True) -> None:
    """Walk through input_dir and write metadata to SQLite DB or CSV.

    For SQLite mode, entries are written and committed one-by-one so that
    a crash at any point never loses already-computed data.  Re-running
    the scan safely picks up where it left off (INSERT OR REPLACE).
    """
    input_dir = os.path.abspath(input_dir)
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

    if use_db:
        # --- SQLite streaming mode: insert + commit each entry immediately ---
        conn = init_db(output_path)
        # Delete previous scan results for this root first
        conn.execute("DELETE FROM photos WHERE scan_root = ?", (input_dir,))
        conn.commit()

        last_pct = -1
        for idx, (root, name, ext) in enumerate(file_list):
            # Progress indicator — update every 5%
            pct = idx * 100 // total_files
            if pct >= last_pct + 5 or idx == 0:
                print(f"  Scanning... {idx}/{total_files} ({pct}%)")
                last_pct = pct

            full_path = os.path.join(root, name)
            try:
                lstat = os.lstat(full_path)
            except OSError:
                continue

            # Skip symbolic links (avoid infinite loops and double-counting)
            if os.path.islink(full_path):
                continue

            try:
                stat = os.stat(full_path)
            except OSError:
                continue

            size_bytes = stat.st_size
            # Skip zero-byte files (empty placeholders or iCloud stubs)
            if size_bytes == 0:
                continue

            entry = _compute_entry(full_path, name, ext, stat, input_dir, scan_time)
            _insert_entry(conn, entry)
            conn.commit()  # Commit every entry — zero data loss on crash

            cat = entry["category"]
            categories[cat] = categories.get(cat, 0) + 1
            if entry["extension"] in ("heic", "heif"):
                heic_count += 1

        conn.close()

        # Stats
        total = sum(categories.values())
        print(f"Index written to SQLite: {output_path}")
        print(f"  Total: {total} files")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}")
        if not HEIC_SUPPORT and heic_count > 0:
            print(f"  ⚠️  {heic_count} HEIC/HEIF files found — install pillow-heif for full support:")
            print(f"      pip install pillow-heif")
    else:
        # --- CSV mode: still needs to build list first ---
        entries = []
        last_pct = -1
        for idx, (root, name, ext) in enumerate(file_list):
            pct = idx * 100 // total_files
            if pct >= last_pct + 5 or idx == 0:
                print(f"  Scanning... {idx}/{total_files} ({pct}%)")
                last_pct = pct

            full_path = os.path.join(root, name)
            try:
                lstat = os.lstat(full_path)
            except OSError:
                continue

            if os.path.islink(full_path):
                continue

            try:
                stat = os.stat(full_path)
            except OSError:
                continue

            size_bytes = stat.st_size
            if size_bytes == 0:
                continue

            entry = _compute_entry(full_path, name, ext, stat, input_dir, scan_time)
            entries.append(entry)

        fieldnames = list(entries[0].keys()) if entries else []
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in entries:
                writer.writerow(row)
        print(f"Index written to CSV: {output_path} ({len(entries)} files)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan photos/videos and build metadata index (SQLite or CSV)")
    parser.add_argument("--input", required=True, help="Directory to scan")
    parser.add_argument("--output", required=True, help="Output path (.db for SQLite, .csv for CSV)")
    parser.add_argument("--format", choices=["auto", "db", "csv"], default="auto",
                        help="Output format (default: auto-detect from file extension)")
    args = parser.parse_args()

    input_dir = os.path.abspath(args.input)
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

    scan_directory(input_dir, output_path, use_db=use_db)


if __name__ == "__main__":
    main()
