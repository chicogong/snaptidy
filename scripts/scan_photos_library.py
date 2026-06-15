#!/usr/bin/env python3
"""Scan macOS Photos.app library and build a metadata index.

Reads the Photos.sqlite database inside a .photoslibrary bundle to extract
rich metadata not available from file-system scanning alone:

* Album membership — which albums each photo belongs to
* Favorite / Hidden flags — from Photos.app's own metadata
* Screenshot detection — Photos.app's built-in classification
* Duplicate visibility — Photos.app's duplicate detection state
* iCloud state — whether the photo is local or cloud-only

Then enriches with SHA-256, pHash, and EXIF from the actual files.

Output is compatible with scan_photos.py's SQLite format, so all downstream
scripts (find_exact_duplicates, find_similar_photos, generate_move_plan)
work seamlessly.

SAFETY: This script is READ-ONLY — it never modifies Photos.sqlite or any
photo file. It only reads metadata.
"""

import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta

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

# Optional HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False

# Core Data epoch: 2001-01-01 00:00:00 UTC
CORE_DATA_EPOCH = datetime(2001, 1, 1)

IMAGE_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff", "heic", "heif",
    "webp", "dng", "cr2", "nef", "arw",
}
VIDEO_EXTS = {
    "mov", "mp4", "m4v", "avi", "mkv", "3gp", "mpg", "mpeg",
    "hevc", "wmv", "flv",
}


def core_data_to_iso(timestamp: float) -> str:
    """Convert Core Data timestamp (seconds since 2001-01-01) to ISO format."""
    try:
        dt = CORE_DATA_EPOCH + timedelta(seconds=timestamp)
        return dt.isoformat()
    except Exception:
        return ""


def compute_sha256(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def compute_phash(path: str) -> str:
    """Compute perceptual hash for an image."""
    try:
        with Image.open(path) as img:
            return str(imagehash.average_hash(img.convert("RGB")))
    except Exception:
        return ""


def get_image_size(path: str) -> tuple:
    """Return (width, height) or ('', '')."""
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return "", ""


def get_exif_datetime(path: str) -> str:
    """Extract DateTimeOriginal from EXIF."""
    try:
        exif_dict = piexif.load(path)
        dt = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if not dt:
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
        pass
    return ""


def get_subsec_time(path: str) -> str:
    """Extract SubSecTimeOriginal from EXIF."""
    try:
        exif_dict = piexif.load(path)
        subsec = exif_dict.get("Exif", {}).get(piexif.ExifIFD.SubSecTimeOriginal)
        if not subsec:
            subsec = exif_dict.get("Exif", {}).get(piexif.ExifIFD.SubSecTime)
        if subsec:
            if isinstance(subsec, bytes):
                subsec = subsec.decode(errors="ignore")
            return str(subsec).strip().rstrip("\x00")
    except Exception:
        pass
    return ""


def get_gps_coords(path: str) -> tuple:
    """Extract GPS coordinates from EXIF."""
    try:
        exif_dict = piexif.load(path)
        gps_ifd = exif_dict.get("GPS", {})
        if not gps_ifd:
            return "", ""

        def _convert_to_degrees(value):
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
    """Extract camera make/model from EXIF."""
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
    """Check if the file has meaningful EXIF data."""
    try:
        exif_dict = piexif.load(path)
        has_exif_section = bool(exif_dict.get("Exif"))
        has_gps = bool(exif_dict.get("GPS"))
        zeroth = exif_dict.get("0th", {})
        has_camera = bool(zeroth.get(piexif.ImageIFD.Make)) or bool(zeroth.get(piexif.ImageIFD.Model))
        return has_exif_section or has_gps or has_camera
    except Exception:
        return False


def get_format_family(ext: str) -> str:
    """Group file extension into format family."""
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
    """Compute width/height ratio."""
    try:
        w = int(width)
        h = int(height)
        if w > 0 and h > 0:
            return f"{w / h:.3f}"
    except (ValueError, TypeError):
        pass
    return ""


def scan_photos_library(library_path: str, output_path: str) -> None:
    """Scan a Photos Library and write metadata to SQLite DB."""
    library_path = os.path.abspath(library_path)
    db_path = os.path.join(library_path, "database", "Photos.sqlite")
    originals_dir = os.path.join(library_path, "originals")

    if not os.path.exists(db_path):
        print(f"Error: Photos.sqlite not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    # Read Photos.sqlite
    photos_db = sqlite3.connect(db_path)
    photos_db.row_factory = sqlite3.Row

    # Get album membership (asset PK -> list of album titles)
    album_map = {}  # asset_pk -> [album_title, ...]
    try:
        cursor = photos_db.execute("""
            SELECT ja.Z_3ASSETS AS asset_pk, ga.ZTITLE AS album_title
            FROM Z_33ASSETS ja
            JOIN ZGENERICALBUM ga ON ja.Z_33ALBUMS = ga.Z_PK
            WHERE ga.ZTITLE IS NOT NULL AND ga.ZTITLE != ''
        """)
        for row in cursor:
            album_map.setdefault(row["asset_pk"], []).append(row["album_title"])
    except sqlite3.OperationalError:
        # Junction table might not exist in older Photos versions
        pass

    # Get all assets
    cursor = photos_db.execute("""
        SELECT Z_PK, ZDIRECTORY, ZFILENAME, ZHEIGHT, ZWIDTH,
               ZFAVORITE, ZHIDDEN, ZKIND, ZISDETECTEDSCREENSHOT,
               ZDUPLICATEASSETVISIBILITYSTATE, ZDATECREATED,
               ZHDRTYPE, ZCLOUDLOCALSTATE
        FROM ZASSET
        WHERE ZTRASHEDSTATE = 0
    """)

    entries = []
    scan_time = datetime.now().isoformat()
    stats = {"total": 0, "photo": 0, "video": 0, "screenshot": 0, "favorite": 0, "skipped_not_found": 0}

    for row in cursor:
        pk = row["Z_PK"]
        directory = row["ZDIRECTORY"] or ""
        filename = row["ZFILENAME"] or ""
        kind = row["ZKIND"] or 0  # 0=photo, 1=video
        is_screenshot = row["ZISDETECTEDSCREENSHOT"] or 0
        is_favorite = row["ZFAVORITE"] or 0
        is_hidden = row["ZHIDDEN"] or 0
        dup_visibility = row["ZDUPLICATEASSETVISIBILITYSTATE"] or 0
        date_created = row["ZDATECREATED"] or 0
        hdr_type = row["ZHDRTYPE"] or 0
        cloud_state = row["ZCLOUDLOCALSTATE"] or 0

        # Build file path
        if directory and filename:
            file_path = os.path.join(originals_dir, directory, filename)
        else:
            continue

        # Check if file exists
        if not os.path.exists(file_path):
            stats["skipped_not_found"] += 1
            continue

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue

        stats["total"] += 1

        # Determine category
        if is_screenshot:
            category = "screenshot"
        elif kind == 1:  # video
            category = "video"
        elif hdr_type and hdr_type > 0:
            category = "burst"
        else:
            category = "photo"

        if is_favorite:
            stats["favorite"] += 1
        if category == "screenshot":
            stats["screenshot"] += 1
        if category == "video":
            stats["video"] += 1
        else:
            stats["photo"] += 1

        # Album membership
        albums = album_map.get(pk, [])
        album_str = "; ".join(albums) if albums else ""

        # Enrich with file-system metadata
        try:
            stat = os.stat(file_path)
            size_bytes = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
        except OSError:
            size_bytes = 0
            mtime = ""

        # Photos.app dimensions (fallback to file if needed)
        pa_width = row["ZWIDTH"] or ""
        pa_height = row["ZHEIGHT"] or ""

        # File-level metadata (only for images)
        exif_dt = ""
        phash = ""
        gps_lat = ""
        gps_lon = ""
        camera_make = ""
        camera_model = ""
        has_exif_val = 0
        width = str(pa_width) if pa_width else ""
        height = str(pa_height) if pa_height else ""
        subsec_time = ""
        aspect_ratio = compute_aspect_ratio(width, height)
        format_family = get_format_family(ext)

        if ext in IMAGE_EXTS:
            exif_dt = get_exif_datetime(file_path)
            subsec_time = get_subsec_time(file_path)
            # Use file dimensions if Photos.app didn't provide them
            if not width or not height:
                fw, fh = get_image_size(file_path)
                width = str(fw) if fw else width
                height = str(fh) if fh else height
                aspect_ratio = compute_aspect_ratio(width, height)
            phash = compute_phash(file_path)
            gps_lat, gps_lon = get_gps_coords(file_path)
            camera_make, camera_model = get_camera_info(file_path)
            has_exif_val = 1 if has_exif_data(file_path) else 0

        sha256 = compute_sha256(file_path)

        # Convert Core Data date
        date_iso = core_data_to_iso(date_created) if date_created else ""
        exif_dt = exif_dt or date_iso  # Prefer EXIF, fall back to Photos.app date

        entries.append({
            "file_path": file_path,
            "filename": filename,
            "extension": ext,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "exif_datetime": exif_dt,
            "file_mtime": mtime,
            "width": width,
            "height": height,
            "phash": phash,
            "media_type": "video" if kind == 1 else "image",
            "category": category,
            "gps_latitude": gps_lat,
            "gps_longitude": gps_lon,
            "camera_make": camera_make,
            "camera_model": camera_model,
            "has_exif": has_exif_val,
            "folder_tag": album_str or directory,  # Use album name as folder_tag
            "scan_root": library_path,
            "scanned_at": scan_time,
            "aspect_ratio": aspect_ratio,
            "subsec_time": subsec_time,
            "format_family": format_family,
            # Photos.app exclusive fields
            "photos_favorite": is_favorite,
            "photos_hidden": is_hidden,
            "photos_screenshot": is_screenshot,
            "photos_duplicate_visibility": dup_visibility,
            "photos_cloud_state": cloud_state,
            "photos_albums": album_str,
        })

    photos_db.close()

    # Write to output SQLite
    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA journal_mode=WAL")
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
            scanned_at TEXT DEFAULT '',
            aspect_ratio TEXT DEFAULT '',
            subsec_time TEXT DEFAULT '',
            format_family TEXT DEFAULT '',
            photos_favorite INTEGER DEFAULT 0,
            photos_hidden INTEGER DEFAULT 0,
            photos_screenshot INTEGER DEFAULT 0,
            photos_duplicate_visibility INTEGER DEFAULT 0,
            photos_cloud_state INTEGER DEFAULT 0,
            photos_albums TEXT DEFAULT ''
        )
    """)
    # Indexes
    for idx in ["idx_sha256", "idx_phash", "idx_category", "idx_exif_datetime",
                "idx_folder_tag", "idx_camera_model", "idx_aspect_ratio",
                "idx_format_family", "idx_photos_favorite", "idx_photos_albums"]:
        col = idx.replace("idx_", "")
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON photos({col})")

    conn.execute("DELETE FROM photos WHERE scan_root = ?", (library_path,))
    for entry in entries:
        cols = ", ".join(entry.keys())
        placeholders = ", ".join("?" for _ in entry)
        conn.execute(f"INSERT OR REPLACE INTO photos ({cols}) VALUES ({placeholders})",
                     list(entry.values()))
    conn.commit()
    conn.close()

    # Stats
    print(f"Photos Library scanned: {library_path}")
    print(f"  Total: {stats['total']} files")
    print(f"  Photos: {stats['photo']}, Videos: {stats['video']}, Screenshots: {stats['screenshot']}")
    print(f"  Favorites: {stats['favorite']}")
    if stats['skipped_not_found'] > 0:
        print(f"  Skipped (file not found / iCloud-only): {stats['skipped_not_found']}")
    if not HEIC_SUPPORT:
        heic_count = sum(1 for e in entries if e["extension"] in ("heic", "heif"))
        if heic_count > 0:
            print(f"  ⚠️  {heic_count} HEIC files — install pillow-heif for full support:")
            print(f"      pip install pillow-heif")
    print(f"  Output: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan macOS Photos.app library and build metadata index")
    parser.add_argument("--library", required=True,
                        help="Path to .photoslibrary bundle")
    parser.add_argument("--output", required=True,
                        help="Output path (.db for SQLite)")
    args = parser.parse_args()

    library_path = os.path.abspath(args.library)
    output_path = os.path.abspath(args.output)

    if not library_path.endswith(".photoslibrary"):
        print(f"Warning: {library_path} doesn't look like a .photoslibrary bundle", file=sys.stderr)
        print(f"         Continuing anyway...", file=sys.stderr)

    if not os.path.isdir(library_path):
        print(f"Error: {library_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    scan_photos_library(library_path, output_path)


if __name__ == "__main__":
    main()
