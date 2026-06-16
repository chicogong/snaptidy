#!/usr/bin/env python3
"""Quick scan — zero-install entry point using only Python stdlib.

This script works without ANY external dependencies. It uses only:
  hashlib, sqlite3, os, argparse, json, math, datetime

Capabilities:
  * Scan a directory for media files (images + videos)
  * Compute SHA-256 hashes for exact dedup
  * Compute file size statistics
  * Output to SQLite (.db) or JSON (.json)
  * Apple Quality Vector detection (if scanning a Photos.app library)

For full features (pHash, EXIF, GPS), use scan_photos.py or
scan_photos_library.py with optional deps installed.
"""

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
from datetime import datetime

IMAGE_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff", "heic", "heif",
    "webp", "dng", "cr2", "nef", "arw",
}
VIDEO_EXTS = {
    "mov", "mp4", "m4v", "avi", "mkv", "3gp", "mpg", "mpeg",
    "hevc", "wmv", "flv",
}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

# Apple pre-computed ML quality feature keys from ZCOMPUTEDASSETATTRIBUTES
APPLE_QUALITY_KEYS = [
    "ZPLEASANTCOMPOSITIONSCORE", "ZPLEASANTLIGHTINGSCORE",
    "ZPLEASANTPATTERNSCORE", "ZFAILURESCORE", "ZNOISESCORE",
    "ZPLEASANTSYMMETRYSCORE", "ZPLEASANTCOLORHUESCORE",
    "ZPLEASANTWALLPAPERSCORE", "ZHARMONIOUSCOLORSCORE",
    "ZIMMERSIVENESSSCORE", "ZINTERACTIONSCORE",
    "ZPLEASANTPERSPECTIVESCORE", "ZPLEASANTSHARPSCORE",
    "ZPLEASANTPOSTPROCESSINGSCORE", "ZTASTEFULLYBLURREDSCORE",
    "ZWELLFRAMEDSUBJECTSCORE", "ZWELLTIMEDSHOTSCORE",
]


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


def auto_categorize(filename: str, ext: str) -> str:
    """Auto-categorize media file based on filename patterns."""
    lower = filename.lower()
    # Screenshot detection (15+ languages)
    screenshot_kw = [
        "screenshot", "screen shot", "screen_capture", "screencap",
        "截图", "截屏", "スクリーンショット", "스크린샷", "скриншот",
        "captura", "bildschirm", "schermopname",
    ]
    for kw in screenshot_kw:
        if kw in lower:
            return "screenshot"

    # WeChat detection
    wechat_kw = ["mmexport", "wx_camera_", "micromsg", "weixin", "wechat"]
    for kw in wechat_kw:
        if kw in lower:
            return "wechat"

    # Burst detection
    burst_kw = ["_hdr", "_burst", "连拍", "連拍", "버스트"]
    for kw in burst_kw:
        if kw in lower:
            return "burst"

    if ext in VIDEO_EXTS:
        return "video"

    return "photo"


def scan_directory(input_path: str, output_path: str) -> None:
    """Scan a directory and build a zero-dep metadata index."""
    input_path = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)

    if not os.path.isdir(input_path):
        print(f"Error: {input_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Open output DB
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
            media_type TEXT NOT NULL DEFAULT 'image',
            category TEXT NOT NULL DEFAULT 'photo',
            format_family TEXT DEFAULT '',
            folder_tag TEXT DEFAULT '',
            scan_root TEXT DEFAULT '',
            scanned_at TEXT DEFAULT '',
            photos_quality_vector TEXT DEFAULT ''
        )
    """)
    for idx in ["idx_sha256", "idx_category", "idx_format_family"]:
        col = idx.replace("idx_", "")
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON photos({col})")
    conn.commit()

    scan_time = datetime.now().isoformat()
    stats = {"total": 0, "photo": 0, "video": 0, "screenshot": 0,
             "wechat": 0, "burst": 0, "total_size": 0}
    last_pct = -1

    # Collect file list first for progress
    print(f"Scanning: {input_path}")
    file_list = []
    for root, dirs, fnames in os.walk(input_path):
        # Skip hidden, system, and backup directories
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d != "__MACOSX"
                   and d not in ("Original_Backup", ".trashes")]
        for name in fnames:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in MEDIA_EXTS:
                file_list.append((root, name, ext))

    total = len(file_list)
    print(f"  Found {total} media files")

    for idx, (root, name, ext) in enumerate(file_list):
        pct = idx * 100 // total if total > 0 else 100
        if pct >= last_pct + 10 or idx == 0:
            print(f"  Processing... {idx}/{total} ({pct}%)")
            last_pct = pct

        file_path = os.path.join(root, name)
        try:
            size_bytes = os.path.getsize(file_path)
        except OSError:
            continue

        sha256 = compute_sha256(file_path)
        if not sha256:
            continue

        category = auto_categorize(name, ext)
        media_type = "video" if ext in VIDEO_EXTS else "image"
        format_family = get_format_family(ext)
        rel_dir = os.path.relpath(root, input_path)
        folder_tag = rel_dir if rel_dir != "." else ""

        stats["total"] += 1
        stats[category] = stats.get(category, 0) + 1
        stats["total_size"] += size_bytes

        conn.execute(
            "INSERT OR REPLACE INTO photos "
            "(file_path, filename, extension, size_bytes, sha256, "
            "media_type, category, format_family, folder_tag, scan_root, scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_path, name, ext, size_bytes, sha256,
             media_type, category, format_family, folder_tag,
             input_path, scan_time)
        )
        conn.commit()

    conn.close()

    # Stats
    total_mb = stats["total_size"] / (1024 * 1024)
    print(f"\nScan complete!")
    print(f"  Total: {stats['total']} files ({total_mb:.1f} MB)")
    print(f"  Photos: {stats['photo']}, Videos: {stats['video']}")
    if stats['screenshot'] > 0:
        print(f"  Screenshots: {stats['screenshot']}")
    if stats['wechat'] > 0:
        print(f"  WeChat: {stats['wechat']}")
    if stats['burst'] > 0:
        print(f"  Burst: {stats['burst']}")
    print(f"  Output: {output_path}")


def scan_photos_library(library_path: str, output_path: str) -> None:
    """Scan a Photos.app library using only stdlib (SHA-256 + Apple QL vectors)."""
    import shutil
    import tempfile

    library_path = os.path.abspath(library_path)
    db_path = os.path.join(library_path, "database", "Photos.sqlite")
    originals_dir = os.path.join(library_path, "originals")

    if not os.path.exists(db_path):
        print(f"Error: Photos.sqlite not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    # Copy Photos.sqlite safely
    tmp_db_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_db_path = tmp.name
        shutil.copy2(db_path, tmp_db_path)
        photos_db = sqlite3.connect(tmp_db_path)
    except Exception as e:
        print(f"Warning: Could not copy Photos.sqlite ({e})", file=sys.stderr)
        photos_db = sqlite3.connect(db_path)
        if tmp_db_path and os.path.exists(tmp_db_path):
            os.unlink(tmp_db_path)
        tmp_db_path = None
    photos_db.row_factory = sqlite3.Row

    # Read Apple quality vectors
    quality_map = {}
    try:
        available_cols = {row[1] for row in photos_db.execute(
            "PRAGMA table_info(ZCOMPUTEDASSETATTRIBUTES)"
        ).fetchall()}
        quality_cols_present = [k for k in APPLE_QUALITY_KEYS if k in available_cols]
        if quality_cols_present:
            cursor = photos_db.execute(f"""
                SELECT ZASSET, {', '.join(quality_cols_present)}
                FROM ZCOMPUTEDASSETATTRIBUTES
            """)
            for qrow in cursor:
                asset_pk = qrow[0]
                vector = []
                for i in range(len(quality_cols_present)):
                    val = qrow[i + 1]
                    try:
                        vector.append(float(val) if val is not None else 0.0)
                    except (TypeError, ValueError):
                        vector.append(0.0)
                while len(vector) < 17:
                    vector.append(0.0)
                quality_map[asset_pk] = vector[:17]
    except sqlite3.OperationalError:
        pass

    # Get all non-trashed assets
    cursor = photos_db.execute("""
        SELECT Z_PK, ZDIRECTORY, ZFILENAME, ZKIND, ZISDETECTEDSCREENSHOT,
               ZFAVORITE, ZHIDDEN
        FROM ZASSET
        WHERE ZTRASHEDSTATE = 0
    """)

    # Open output DB
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
            media_type TEXT NOT NULL DEFAULT 'image',
            category TEXT NOT NULL DEFAULT 'photo',
            format_family TEXT DEFAULT '',
            folder_tag TEXT DEFAULT '',
            scan_root TEXT DEFAULT '',
            scanned_at TEXT DEFAULT '',
            photos_quality_vector TEXT DEFAULT '',
            photos_favorite INTEGER DEFAULT 0,
            photos_hidden INTEGER DEFAULT 0,
            photos_screenshot INTEGER DEFAULT 0
        )
    """)
    for idx in ["idx_sha256", "idx_category", "idx_format_family",
                "idx_photos_favorite"]:
        col = idx.replace("idx_", "")
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON photos({col})")
    conn.execute("DELETE FROM photos WHERE scan_root = ?", (library_path,))
    conn.commit()

    scan_time = datetime.now().isoformat()
    stats = {"total": 0, "photo": 0, "video": 0, "screenshot": 0,
             "favorite": 0, "with_quality_vector": 0, "skipped": 0}

    for row in cursor:
        pk = row["Z_PK"]
        directory = row["ZDIRECTORY"] or ""
        filename = row["ZFILENAME"] or ""
        kind = row["ZKIND"] or 0
        is_screenshot = row["ZISDETECTEDSCREENSHOT"] or 0
        is_favorite = row["ZFAVORITE"] or 0
        is_hidden = row["ZHIDDEN"] or 0

        if not directory or not filename:
            continue

        file_path = os.path.join(originals_dir, directory, filename)
        if not os.path.exists(file_path):
            stats["skipped"] += 1
            continue

        try:
            if os.path.getsize(file_path) == 0:
                stats["skipped"] += 1
                continue
        except OSError:
            stats["skipped"] += 1
            continue

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue

        stats["total"] += 1
        size_bytes = os.path.getsize(file_path)
        sha256 = compute_sha256(file_path)
        category = "screenshot" if is_screenshot else ("video" if kind == 1 else "photo")
        media_type = "video" if kind == 1 else "image"
        format_family = get_format_family(ext)

        if is_favorite:
            stats["favorite"] += 1
        if category == "screenshot":
            stats["screenshot"] += 1
        if category == "video":
            stats["video"] += 1
        else:
            stats["photo"] += 1

        qv = quality_map.get(pk, [])
        if qv:
            stats["with_quality_vector"] += 1

        conn.execute(
            "INSERT OR REPLACE INTO photos "
            "(file_path, filename, extension, size_bytes, sha256, "
            "media_type, category, format_family, folder_tag, scan_root, "
            "scanned_at, photos_quality_vector, photos_favorite, "
            "photos_hidden, photos_screenshot) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_path, filename, ext, size_bytes, sha256,
             media_type, category, format_family, directory,
             library_path, scan_time, json.dumps(qv),
             is_favorite, is_hidden, is_screenshot)
        )
        conn.commit()

    photos_db.close()
    if tmp_db_path and os.path.exists(tmp_db_path):
        try:
            os.unlink(tmp_db_path)
        except OSError:
            pass

    conn.close()

    print(f"Photos Library scanned: {library_path}")
    print(f"  Total: {stats['total']} files")
    print(f"  Photos: {stats['photo']}, Videos: {stats['video']}, Screenshots: {stats['screenshot']}")
    print(f"  Favorites: {stats['favorite']}")
    if stats['with_quality_vector'] > 0:
        print(f"  With Apple quality vector: {stats['with_quality_vector']} (zero-dep similarity)")
    if stats['skipped'] > 0:
        print(f"  Skipped: {stats['skipped']}")
    print(f"  Output: {output_path}")


def find_exact_duplicates(index_path: str, output_path: str = None) -> list:
    """Find exact duplicates by SHA-256 in the scanned index."""
    conn = sqlite3.connect(index_path)
    cursor = conn.execute("""
        SELECT sha256, file_path, size_bytes, category
        FROM photos
        WHERE sha256 != '' AND sha256 IS NOT NULL
        AND sha256 IN (
            SELECT sha256 FROM photos
            WHERE sha256 != '' AND sha256 IS NOT NULL
            GROUP BY sha256
            HAVING COUNT(*) > 1
        )
        ORDER BY sha256, file_path
    """)

    groups = {}
    for sha256, path, size, category in cursor:
        groups.setdefault(sha256, []).append({
            "file_path": path, "size_bytes": size, "category": category
        })
    conn.close()

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now().isoformat(),
                "total_groups": len(groups),
                "total_duplicate_files": sum(len(v) for v in groups.values()),
                "groups": {k: v for k, v in groups.items()}
            }, f, indent=2, ensure_ascii=False)

    return groups


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SnapTidy Quick Scan — zero-install entry point (stdlib only)")
    parser.add_argument("--input", help="Path to photo/video directory to scan")
    parser.add_argument("--library",
                        help="Path to .photoslibrary bundle (Photos.app scan)")
    parser.add_argument("--output", required=True,
                        help="Output path (.db for SQLite)")
    parser.add_argument("--dedup", action="store_true",
                        help="Also find exact duplicates (SHA-256)")
    parser.add_argument("--dedup-output",
                        help="Output path for dedup results (JSON, only with --dedup)")
    args = parser.parse_args()

    if not args.input and not args.library:
        parser.error("Either --input or --library is required")

    if args.library:
        scan_photos_library(args.library, args.output)
    else:
        scan_directory(args.input, args.output)

    if args.dedup:
        dedup_output = args.dedup_output or args.output.replace(".db", "_dedup.json")
        groups = find_exact_duplicates(args.output, dedup_output)
        total_dups = sum(len(v) for v in groups.values())
        waste = sum(v[0]["size_bytes"] * (len(v) - 1) for v in groups.values() if v)
        waste_mb = waste / (1024 * 1024)
        print(f"\nExact duplicates: {total_dups} files in {len(groups)} groups")
        print(f"  Wasted space: {waste_mb:.1f} MB")
        print(f"  Dedup report: {dedup_output}")


if __name__ == "__main__":
    main()
