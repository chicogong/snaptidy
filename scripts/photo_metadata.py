#!/usr/bin/env python3
"""Shared photo metadata helpers — the single source of truth.

This module consolidates the hashing, EXIF, perceptual-hash, dimension and
format helpers that were previously copy-pasted across scan_photos.py,
scan_photos_library.py, quick_scan.py and import_to_photos.py.

All optional third-party dependencies (Pillow, piexif, imagehash,
pillow-heif) are imported defensively here so every consumer shares one
set of availability flags instead of re-declaring them.

The functions intentionally never raise on bad input — they return empty
strings / tuples so callers can keep scanning a large library even when a
single file is corrupt or in an unsupported format.
"""

import hashlib
from datetime import datetime

# ---------------------------------------------------------------------------
# Optional dependency probing (shared by all consumers)
# ---------------------------------------------------------------------------
try:
    from PIL import Image
    PILLOW_AVAILABLE = True
    # Decompression bomb protection — reject images that exceed ~60 MP
    # (prevents OOM from malicious crafted files)
    Image.MAX_IMAGE_PIXELS = 60_000_000  # 60 megapixels
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

# Optional HEIC/HEIF decode support via pillow-heif
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False

# Optional AVIF decode support (Pillow >= 11 has native AVIF; older needs pillow-avif-plugin)
try:
    # Test if Pillow can already open AVIF natively
    import io
    _avif_test = Image.open(io.BytesIO(b"\x00\x00\x00\x20ftypavif"))
    AVIF_SUPPORT = True
except Exception:
    try:
        import pillow_avif  # noqa: F401
        AVIF_SUPPORT = True
    except ImportError:
        AVIF_SUPPORT = False


def missing_dependencies() -> list:
    """Return a list of optional deps that are NOT installed (for warnings)."""
    missing = []
    if not PILLOW_AVAILABLE:
        missing.append("Pillow")
    if not PIEXIF_AVAILABLE:
        missing.append("piexif")
    if not IMAGEHASH_AVAILABLE:
        missing.append("imagehash")
    if not HEIC_SUPPORT:
        missing.append("pillow-heif")
    if not AVIF_SUPPORT:
        missing.append("pillow-avif-plugin")
    return missing


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def compute_sha256(path: str) -> str:
    """Compute the SHA-256 hash of a file in 64 KiB chunks.

    Returns the hex digest, or '' if the file cannot be read.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Perceptual hash & dimensions
# ---------------------------------------------------------------------------
def compute_phash(path: str) -> str:
    """Compute the average perceptual hash for an image.

    Returns a hex string, or '' if the image cannot be opened or the
    required libraries are unavailable.
    """
    if not PILLOW_AVAILABLE or not IMAGEHASH_AVAILABLE:
        return ""
    try:
        with Image.open(path) as img:
            return str(imagehash.average_hash(img.convert("RGB")))
    except Exception:
        return ""


def get_image_size(path: str) -> tuple:
    """Return (width, height) of an image, or ('', '') on failure."""
    if not PILLOW_AVAILABLE:
        return "", ""
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return "", ""


def compute_aspect_ratio(width, height) -> str:
    """Compute width/height ratio rounded to 3 decimals, or '' if invalid."""
    try:
        w = int(width)
        h = int(height)
        if w > 0 and h > 0:
            return f"{w / h:.3f}"
    except (ValueError, TypeError):
        pass
    return ""


# ---------------------------------------------------------------------------
# EXIF helpers
# ---------------------------------------------------------------------------
def get_exif_datetime(path: str) -> str:
    """Extract DateTimeOriginal from EXIF.  Returns ISO string or ''."""
    if not PIEXIF_AVAILABLE:
        return ""
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
        pass
    return ""


def get_subsec_time(path: str) -> str:
    """Extract SubSecTimeOriginal from EXIF (for burst grouping).  Returns ''."""
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
    """Extract GPS latitude/longitude from EXIF.  Returns (lat, lon) or ('', '')."""
    if not PIEXIF_AVAILABLE:
        return "", ""
    try:
        exif_dict = piexif.load(path)
        gps_ifd = exif_dict.get("GPS", {})
        if not gps_ifd:
            return "", ""

        def _convert_to_degrees(value):
            """Convert GPS (degrees, minutes, seconds) rationals to decimal."""
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
    """Extract camera (make, model) from EXIF.  Returns ('', '') on failure."""
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
    """Return True if the file carries meaningful EXIF (camera/GPS/exposure)."""
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


# ---------------------------------------------------------------------------
# Animated image detection
# ---------------------------------------------------------------------------
def is_animated_image(path: str) -> bool:
    """Check if an image is animated (GIF, animated WebP, APNG).

    Returns True for multi-frame images, False for static images.
    """
    if not PILLOW_AVAILABLE:
        return False
    try:
        with Image.open(path) as img:
            # GIF: check n_frames
            if getattr(img, "n_frames", 1) > 1:
                return True
            # WebP: check is_animated attribute (Pillow >= 6.1)
            if hasattr(img, "is_animated") and img.is_animated:
                return True
            # APNG: check for multiple frames in PNG
            if img.format == "PNG":
                # APNG stores frames in acTL chunk; Pillow detects via n_frames
                if getattr(img, "n_frames", 1) > 1:
                    return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# EXIF Orientation helpers
# ---------------------------------------------------------------------------
def get_exif_orientation(path: str) -> int:
    """Extract EXIF Orientation value (1-8).

    Values:
      1 = Normal (no rotation)
      2 = Mirrored horizontal
      3 = Rotated 180°
      4 = Mirrored vertical
      5 = Mirrored horizontal + rotated 270°
      6 = Rotated 90° (most common from iPhone portrait)
      7 = Mirrored horizontal + rotated 90°
      8 = Rotated 270°

    Returns orientation int, or 1 if not found / not applicable.
    """
    if not PIEXIF_AVAILABLE:
        return 1
    try:
        exif_dict = piexif.load(path)
        orientation = exif_dict.get("0th", {}).get(piexif.ImageIFD.Orientation, 1)
        return int(orientation) if orientation else 1
    except Exception:
        return 1


# EXIF orientation → PIL transform mapping
_ORIENT_TRANSFORMATION = {
    1: None,                       # Normal
    2: Image.FLIP_LEFT_RIGHT,      # Mirrored horizontal
    3: Image.ROTATE_180,           # Rotated 180°
    4: Image.FLIP_TOP_BOTTOM,      # Mirrored vertical
    5: Image.TRANSPOSE,            # Mirrored horizontal + rotated 270°
    6: Image.ROTATE_270,           # Rotated 90° (pillow uses CCW)
    7: Image.TRANSVERSE,           # Mirrored horizontal + rotated 90°
    8: Image.ROTATE_90,            # Rotated 270° (pillow uses CCW)
}


def apply_exif_orientation(path: str, output_path: str = None, quality: int = 95) -> bool:
    """Apply EXIF orientation to image pixels and reset orientation to 1.

    If output_path is None, overwrites the original file.
    Returns True on success, False on failure.
    """
    if not PILLOW_AVAILABLE or not PIEXIF_AVAILABLE:
        return False
    try:
        orientation = get_exif_orientation(path)
        if orientation <= 1:
            return True  # Already correct, no rotation needed

        transform = _ORIENT_TRANSFORMATION.get(orientation)
        if transform is None:
            return True

        with Image.open(path) as img:
            rotated = img.transpose(transform) if transform else img

            # Preserve EXIF but set orientation to 1 (normal)
            if "exif" in img.info:
                exif_dict = piexif.load(img.info["exif"])
                exif_dict["0th"][piexif.ImageIFD.Orientation] = 1
                exif_bytes = piexif.dump(exif_dict)
            else:
                exif_bytes = None

            save_path = output_path or path
            fmt = img.format or "JPEG"

            save_kwargs = {"quality": quality}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes

            if fmt == "JPEG":
                rotated.save(save_path, format="JPEG", **save_kwargs)
            else:
                rotated.save(save_path, format=fmt, **save_kwargs)

        return True
    except Exception:
        return False
