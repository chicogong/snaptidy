#!/usr/bin/env python3
"""Shared constants and small pure helpers — the single source of truth.

Consolidates values that were previously redefined across multiple scripts:
file-extension sets, format-family grouping, the Core Data epoch, month
names, album-name maps and human-readable size formatting.
"""

from datetime import datetime

# ---------------------------------------------------------------------------
# File extensions (single source of truth — always WITHOUT leading dot)
# ---------------------------------------------------------------------------

RAW_EXTS = {"dng", "cr2", "nef", "arw", "orf", "rw2", "raf", "srw", "raw"}

IMAGE_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff",
    "heic", "heif", "webp", "avif", "ico",
    "ppm", "pgm", "pbm",
} | RAW_EXTS

VIDEO_EXTS = {
    "mov", "mp4", "m4v", "avi", "mkv", "3gp", "mpg", "mpeg",
    "hevc", "wmv", "flv", "webm", "mts", "m2ts",
}

# Convenient subsets (no leading dot)
JPEG_EXTS = {"jpg", "jpeg"}
HEIC_EXTS = {"heic", "heif"}
AVIF_EXTS = {"avif"}

# Combined media set
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

# Dot-prefixed variants for direct comparison with Path.suffix output
IMAGE_EXTENSIONS = {f".{e}" for e in IMAGE_EXTS}
VIDEO_EXTENSIONS = {f".{e}" for e in VIDEO_EXTS}
PHOTO_EXTENSIONS = {f".{e}" for e in MEDIA_EXTS}
JPEG_EXTENSIONS = {f".{e}" for e in JPEG_EXTS}
HEIC_EXTENSIONS = {f".{e}" for e in HEIC_EXTS}
AVIF_EXTENSIONS = {f".{e}" for e in AVIF_EXTS}

# ---------------------------------------------------------------------------
# Core Data epoch (Apple Photos.sqlite timestamps): 2001-01-01 00:00:00 UTC
# ---------------------------------------------------------------------------
CORE_DATA_EPOCH = datetime(2001, 1, 1)

# ---------------------------------------------------------------------------
# Month names (for date-based album naming and reports)
# ---------------------------------------------------------------------------
MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

# ---------------------------------------------------------------------------
# Album name maps (with emoji prefixes for visual distinction in Photos.app)
# ---------------------------------------------------------------------------
CATEGORY_ALBUM_NAMES = {
    "photo": "📸 Photos",
    "screenshot": "📱 Screenshots",
    "wechat": "💬 WeChat",
    "burst": "🔄 Burst",
    "video": "🎬 Videos",
    "live_photo": "🎵 Live Photos",
}

FORMAT_ALBUM_NAMES = {
    "jpeg": "JPEG",
    "heic": "HEIC",
    "heif": "HEIF",
    "png": "PNG",
    "gif": "GIF",
    "tiff": "TIFF",
    "raw": "RAW",
    "bmp": "BMP",
    "webp": "WebP",
    "avif": "AVIF",
    "other": "Other",
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def get_format_family(ext: str) -> str:
    """Group a file extension into a format family for cross-format dedup."""
    ext_lower = ext.lower().lstrip(".")
    if ext_lower in ("jpg", "jpeg"):
        return "jpeg"
    elif ext_lower in ("heic", "heif"):
        return "heic"
    elif ext_lower == "png":
        return "png"
    elif ext_lower in ("tif", "tiff"):
        return "tiff"
    elif ext_lower in RAW_EXTS:
        return "raw"
    elif ext_lower == "webp":
        return "webp"
    elif ext_lower == "avif":
        return "avif"
    else:
        return "other"


def format_size(num_bytes) -> str:
    """Format a byte count as a human-readable string (B / KB / MB / GB / TB)."""
    try:
        size = float(num_bytes)
    except (ValueError, TypeError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


# Backwards-compatible alias (organize_photos.py historically used this name)
format_bytes = format_size


def core_data_to_iso(timestamp: float) -> str:
    """Convert a Core Data timestamp (seconds since 2001-01-01) to ISO format."""
    from datetime import timedelta
    try:
        return (CORE_DATA_EPOCH + timedelta(seconds=timestamp)).isoformat()
    except Exception:
        return ""
