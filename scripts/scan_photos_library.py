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
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

try:
    import piexif
    PIEXIF_AVAILABLE = True
except ImportError:
    PIEXIF_AVAILABLE = False

try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False

# Optional HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False

# Core Data epoch: 2001-01-01 00:00:00 UTC
CORE_DATA_EPOCH = datetime(2001, 1, 1)

# Apple pre-computed ML quality feature keys from ZCOMPUTEDASSETATTRIBUTES
# These 17 scores are computed by Apple's Vision framework on import,
# enabling zero-dependency similarity detection via cosine similarity.
APPLE_QUALITY_KEYS = [
    "ZPLEASANTCOMPOSITIONSCORE",
    "ZPLEASANTLIGHTINGSCORE",
    "ZPLEASANTPATTERNSCORE",
    "ZFAILURESCORE",
    "ZNOISESCORE",
    "ZPLEASANTSYMMETRYSCORE",
    "ZPLEASANTCOLORHUESCORE",
    "ZPLEASANTWALLPAPERSCORE",
    "ZHARMONIOUSCOLORSCORE",
    "ZIMMERSIVENESSSCORE",
    "ZINTERACTIONSCORE",
    "ZPLEASANTPERSPECTIVESCORE",
    "ZPLEASANTSHARPSCORE",
    "ZPLEASANTPOSTPROCESSINGSCORE",
    "ZTASTEFULLYBLURREDSCORE",
    "ZWELLFRAMEDSUBJECTSCORE",
    "ZWELLTIMEDSHOTSCORE",
]

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
    """Compute perceptual hash for an image. Returns '' if imagehash not installed."""
    if not IMAGEHASH_AVAILABLE or not PILLOW_AVAILABLE:
        return ""
    try:
        with Image.open(path) as img:
            return str(imagehash.average_hash(img.convert("RGB")))
    except Exception:
        return ""


def get_image_size(path: str) -> tuple:
    """Return (width, height) or ('', ''). Returns ('', '') if Pillow not installed."""
    if not PILLOW_AVAILABLE:
        return "", ""
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return "", ""


def get_exif_datetime(path: str) -> str:
    """Extract DateTimeOriginal from EXIF. Returns '' if piexif not installed."""
    if not PIEXIF_AVAILABLE:
        return ""
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
    """Extract SubSecTimeOriginal from EXIF. Returns '' if piexif not installed."""
    if not PIEXIF_AVAILABLE:
        return ""
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
    """Extract GPS coordinates from EXIF. Returns ('', '') if piexif not installed."""
    if not PIEXIF_AVAILABLE:
        return "", ""
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
    """Extract camera make/model from EXIF. Returns ('', '') if piexif not installed."""
    if not PIEXIF_AVAILABLE:
        return "", ""
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
    """Check if the file has meaningful EXIF data. Returns False if piexif not installed."""
    if not PIEXIF_AVAILABLE:
        return False
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


def _open_output_db(output_path: str) -> sqlite3.Connection:
    """Open and initialize the output SQLite database."""
    conn = sqlite3.connect(output_path)
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
            scanned_at TEXT DEFAULT '',
            aspect_ratio TEXT DEFAULT '',
            subsec_time TEXT DEFAULT '',
            format_family TEXT DEFAULT '',
            photos_favorite INTEGER DEFAULT 0,
            photos_hidden INTEGER DEFAULT 0,
            photos_screenshot INTEGER DEFAULT 0,
            photos_duplicate_visibility INTEGER DEFAULT 0,
            photos_cloud_state INTEGER DEFAULT 0,
            photos_albums TEXT DEFAULT '',
            photos_shared_albums TEXT DEFAULT '',
            photos_icloud_locally_available INTEGER DEFAULT -1,
            photos_quality_vector TEXT DEFAULT ''
        )
    """)
    # Add missing columns (e.g. when re-scanning over a directory-scan DB)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
    defined_cols = [
        ("exif_datetime", "TEXT DEFAULT ''"), ("file_mtime", "TEXT DEFAULT ''"),
        ("width", "TEXT DEFAULT ''"), ("height", "TEXT DEFAULT ''"),
        ("phash", "TEXT DEFAULT ''"), ("media_type", "TEXT NOT NULL DEFAULT 'image'"),
        ("category", "TEXT NOT NULL DEFAULT 'photo'"),
        ("gps_latitude", "TEXT DEFAULT ''"), ("gps_longitude", "TEXT DEFAULT ''"),
        ("camera_make", "TEXT DEFAULT ''"), ("camera_model", "TEXT DEFAULT ''"),
        ("has_exif", "INTEGER DEFAULT 0"), ("folder_tag", "TEXT DEFAULT ''"),
        ("scan_root", "TEXT DEFAULT ''"), ("scanned_at", "TEXT DEFAULT ''"),
        ("aspect_ratio", "TEXT DEFAULT ''"), ("subsec_time", "TEXT DEFAULT ''"),
        ("format_family", "TEXT DEFAULT ''"),
        ("photos_favorite", "INTEGER DEFAULT 0"),
        ("photos_hidden", "INTEGER DEFAULT 0"),
        ("photos_screenshot", "INTEGER DEFAULT 0"),
        ("photos_duplicate_visibility", "INTEGER DEFAULT 0"),
        ("photos_cloud_state", "INTEGER DEFAULT 0"),
        ("photos_albums", "TEXT DEFAULT ''"),
        ("photos_shared_albums", "TEXT DEFAULT ''"),
        ("photos_icloud_locally_available", "INTEGER DEFAULT -1"),
        ("photos_quality_vector", "TEXT DEFAULT ''"),
    ]
    for col_name, col_type in defined_cols:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col_name} {col_type}")

    # Indexes — only on columns that actually exist
    all_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
    for idx in ["idx_sha256", "idx_phash", "idx_category", "idx_exif_datetime",
                "idx_folder_tag", "idx_camera_model", "idx_aspect_ratio",
                "idx_format_family", "idx_photos_favorite", "idx_photos_albums",
                "idx_photos_shared_albums", "idx_photos_icloud_locally_available"]:
        col = idx.replace("idx_", "")
        if col in all_cols:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON photos({col})")
    conn.commit()
    return conn


def _insert_entry(conn, entry: dict):
    """Insert a single entry into the photos table (does NOT commit)."""
    cols = ", ".join(entry.keys())
    placeholders = ", ".join("?" for _ in entry)
    conn.execute(f"INSERT OR REPLACE INTO photos ({cols}) VALUES ({placeholders})",
                 list(entry.values()))


def scan_photos_library(library_path: str, output_path: str) -> None:
    """Scan a Photos Library and write metadata to SQLite DB."""
    library_path = os.path.abspath(library_path)
    db_path = os.path.join(library_path, "database", "Photos.sqlite")
    originals_dir = os.path.join(library_path, "originals")

    if not os.path.exists(db_path):
        print(f"Error: Photos.sqlite not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    # SAFETY: Copy Photos.sqlite to temp file before querying
    # to avoid locking issues if Photos.app is running
    tmp_db_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_db_path = tmp.name
        shutil.copy2(db_path, tmp_db_path)
        print(f"  Using copy of Photos.sqlite (safe read)")
        photos_db = sqlite3.connect(tmp_db_path)
    except Exception as e:
        print(f"Warning: Could not copy Photos.sqlite ({e}), using direct connection", file=sys.stderr)
        photos_db = sqlite3.connect(db_path)
        if tmp_db_path and os.path.exists(tmp_db_path):
            os.unlink(tmp_db_path)
        tmp_db_path = None
    photos_db.row_factory = sqlite3.Row

    # Get album membership (asset PK -> list of album titles)
    album_map = {}  # asset_pk -> [album_title, ...]
    shared_album_map = {}  # asset_pk -> [shared_album_title, ...]
    try:
        # Dynamically find the album-asset junction table.
        # The correct table (e.g. Z_33ASSETS) has BOTH an "ALBUM" column and an
        # "ASSET" column.  Other Z_%ASSETS tables (Memories, Suggestions) lack
        # an ALBUM column, so we filter by checking the schema.
        candidate_tables = [row[0] for row in photos_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Z_%ASSETS'"
        ).fetchall()]
        junction_table = None
        album_col = None
        asset_col = None
        for t in candidate_tables:
            j_cols = [row[1] for row in photos_db.execute(f"PRAGMA table_info({t})").fetchall()]
            ac = next((c for c in j_cols if "ALBUM" in c.upper()), None)
            asc = next((c for c in j_cols if "ASSET" in c.upper()), None)
            if ac and asc:
                junction_table = t
                album_col = ac
                asset_col = asc
                break
        if not junction_table:
            junction_table = "Z_33ASSETS"

        if album_col and asset_col:
            # Get CloudSharedAlbum Z_ENT value
            shared_ent = None
            try:
                ent_row = photos_db.execute(
                    "SELECT Z_PK FROM Z_PRIMARYKEY WHERE Z_ENTITYNAME = 'CloudSharedAlbum'"
                ).fetchone()
                if ent_row:
                    shared_ent = ent_row[0]
            except sqlite3.OperationalError:
                pass

            cursor = photos_db.execute(f"""
                SELECT ja.{asset_col} AS asset_pk, ga.ZTITLE AS album_title,
                       ga.Z_ENT AS album_ent, ga.ZCLOUDOWNERFULLNAME AS cloud_owner,
                       ga.ZISOWNED AS is_owned
                FROM {junction_table} ja
                JOIN ZGENERICALBUM ga ON ja.{album_col} = ga.Z_PK
                WHERE ga.ZTITLE IS NOT NULL AND ga.ZTITLE != ''
            """)
            for row in cursor:
                is_shared = (shared_ent is not None and row["album_ent"] == shared_ent) or \
                            (row["cloud_owner"] is not None and row["cloud_owner"] != "")
                if is_shared:
                    shared_album_map.setdefault(row["asset_pk"], []).append(row["album_title"])
                else:
                    album_map.setdefault(row["asset_pk"], []).append(row["album_title"])
    except sqlite3.OperationalError:
        # Junction table might not exist in older Photos versions
        pass

    # Get iCloud local availability (from ZCLOUDRESOURCE)
    icloud_available_map = {}  # asset UUID -> is_locally_available
    try:
        cursor = photos_db.execute("""
            SELECT cr.ZASSETUUID, cr.ZISLOCALLYAVAILABLE
            FROM ZCLOUDRESOURCE cr
            WHERE cr.ZISLOCALLYAVAILABLE IS NOT NULL
        """)
        for row in cursor:
            icloud_available_map[row[0]] = bool(row[1])
    except sqlite3.OperationalError:
        pass

    # Get Apple pre-computed ML quality scores (ZCOMPUTEDASSETATTRIBUTES)
    # These enable zero-dependency similarity detection via cosine similarity
    quality_map = {}  # asset_pk -> [17 floats]
    try:
        available_quality_cols = {row[1] for row in photos_db.execute(
            "PRAGMA table_info(ZCOMPUTEDASSETATTRIBUTES)"
        ).fetchall()}
        quality_cols_present = [k for k in APPLE_QUALITY_KEYS if k in available_quality_cols]

        if quality_cols_present:
            cursor = photos_db.execute(f"""
                SELECT ZASSET, {', '.join(quality_cols_present)}
                FROM ZCOMPUTEDASSETATTRIBUTES
            """)
            for qrow in cursor:
                asset_pk = qrow[0]
                vector = []
                for i, col in enumerate(quality_cols_present):
                    val = qrow[i + 1]  # +1 because first column is ZASSET
                    try:
                        vector.append(float(val) if val is not None else 0.0)
                    except (TypeError, ValueError):
                        vector.append(0.0)
                # Pad to 17 dimensions if some columns are missing
                while len(vector) < 17:
                    vector.append(0.0)
                quality_map[asset_pk] = vector[:17]
    except sqlite3.OperationalError:
        pass

    # Get all assets (include ZUUID for iCloud lookup)
    cursor = photos_db.execute("""
        SELECT Z_PK, ZDIRECTORY, ZFILENAME, ZHEIGHT, ZWIDTH,
               ZFAVORITE, ZHIDDEN, ZKIND, ZISDETECTEDSCREENSHOT,
               ZDUPLICATEASSETVISIBILITYSTATE, ZDATECREATED,
               ZHDRTYPE, ZCLOUDLOCALSTATE, ZUUID
        FROM ZASSET
        WHERE ZTRASHEDSTATE = 0
    """)

    entries = []  # Kept only for HEIC count in stats; entries are streamed to DB
    heic_count = 0
    scan_time = datetime.now().isoformat()
    stats = {"total": 0, "photo": 0, "video": 0, "screenshot": 0, "favorite": 0,
             "skipped_not_found": 0, "icloud_only": 0, "in_shared_album": 0,
             "with_quality_vector": 0}

    # Open output DB first (before the asset loop) so we can stream writes
    out_conn = _open_output_db(output_path)
    out_conn.execute("DELETE FROM photos WHERE scan_root = ?", (library_path,))
    out_conn.commit()

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
        asset_uuid = row["ZUUID"] or ""

        # Build file path
        if directory and filename:
            file_path = os.path.join(originals_dir, directory, filename)
        else:
            continue

        # Check if file exists and is not empty
        if not os.path.exists(file_path):
            stats["skipped_not_found"] += 1
            continue

        # Skip zero-byte files (iCloud stubs or corrupted files)
        try:
            if os.path.getsize(file_path) == 0:
                stats["skipped_not_found"] += 1
                continue
        except OSError:
            stats["skipped_not_found"] += 1
            continue

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue

        stats["total"] += 1

        # Album membership (needed for stats before continue)
        albums = album_map.get(pk, [])
        album_str = "; ".join(albums) if albums else ""
        shared_albums = shared_album_map.get(pk, [])
        shared_album_str = "; ".join(shared_albums) if shared_albums else ""

        # Check iCloud local availability (needed for stats)
        icloud_locally_available = None
        if asset_uuid:
            icloud_locally_available = icloud_available_map.get(asset_uuid)

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
        if shared_albums:
            stats["in_shared_album"] += 1
        if quality_map.get(pk):
            stats["with_quality_vector"] += 1
        if icloud_locally_available is False:
            stats["icloud_only"] += 1

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

        entry_dict = {
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
            "photos_shared_albums": shared_album_str,
            "photos_icloud_locally_available": icloud_locally_available,
            "photos_quality_vector": json.dumps(quality_map.get(pk, [])),
        }

        entries.append(entry_dict)

        # Track HEIC count for stats
        if ext in ("heic", "heif"):
            heic_count += 1

        # Stream to output DB immediately — zero data loss on crash
        _insert_entry(out_conn, entry_dict)
        out_conn.commit()

    photos_db.close()

    # Clean up temp copy of Photos.sqlite
    if tmp_db_path and os.path.exists(tmp_db_path):
        try:
            os.unlink(tmp_db_path)
        except OSError:
            pass

    # Close output DB (data was already streamed during the loop)
    out_conn.close()

    # Stats
    print(f"Photos Library scanned: {library_path}")
    print(f"  Total: {stats['total']} files")
    print(f"  Photos: {stats['photo']}, Videos: {stats['video']}, Screenshots: {stats['screenshot']}")
    print(f"  Favorites: {stats['favorite']}")
    if stats['in_shared_album'] > 0:
        print(f"  In shared albums: {stats['in_shared_album']}")
    if stats['icloud_only'] > 0:
        print(f"  iCloud-only (not local): {stats['icloud_only']}")
    if stats['with_quality_vector'] > 0:
        print(f"  With Apple quality vector: {stats['with_quality_vector']} (zero-dep similarity)")
    if stats['skipped_not_found'] > 0:
        print(f"  Skipped (file not found / iCloud-only): {stats['skipped_not_found']}")
    if not HEIC_SUPPORT:
        if heic_count > 0:
            print(f"  ⚠️  {heic_count} HEIC files — install pillow-heif for full support:")
            print(f"      pip install pillow-heif")
    if not PILLOW_AVAILABLE or not PIEXIF_AVAILABLE or not IMAGEHASH_AVAILABLE:
        missing = []
        if not PILLOW_AVAILABLE:
            missing.append("Pillow")
        if not PIEXIF_AVAILABLE:
            missing.append("piexif")
        if not IMAGEHASH_AVAILABLE:
            missing.append("imagehash")
        print(f"  ℹ️  Optional deps not installed: {', '.join(missing)}")
        print(f"      pHash/EXIF/GPS data will be empty (Apple quality vector still available)")
        print(f"      Install with: pip install {' '.join(missing)}")
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
