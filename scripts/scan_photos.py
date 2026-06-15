#!/usr/bin/env python3
"""Scan a folder of photos and videos and build a metadata index.

This script walks a directory tree and collects basic metadata for image and video
files.  The output is a CSV suitable for downstream duplicate detection and
organisation.

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
* is_screenshot – true if the filename/path indicates a screenshot

The script intentionally does not modify any files; it only reads metadata.
"""

import argparse
import csv
import hashlib
import os
import sys
from datetime import datetime

try:
    from PIL import Image
except ImportError:
    print("Pillow is required. Install with pip install Pillow", file=sys.stderr)
    sys.exit(1)

try:
    import piexif
except ImportError:
    print("piexif is required. Install with pip install piexif", file=sys.stderr)
    sys.exit(1)

try:
    import imagehash
except ImportError:
    print("imagehash is required. Install with pip install imagehash", file=sys.stderr)
    sys.exit(1)


IMAGE_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff", "heic", "heif",
}
VIDEO_EXTS = {
    "mov", "mp4", "m4v", "avi", "mkv", "3gp", "mpg", "mpeg",
}


def compute_sha256(path: str) -> str:
    """Compute the SHA‑256 hash of a file in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_exif_datetime(path: str) -> str:
    """Extract DateTimeOriginal from EXIF data if present.  Returns ISO string or ''."""
    try:
        exif_dict = piexif.load(path)
        dt = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if dt:
            # EXIF values may be bytes; decode to string
            if isinstance(dt, bytes):
                dt = dt.decode(errors="ignore")
            # Some cameras append null characters; strip them
            dt_str = dt.replace("\x00", "").strip()
            # EXIF date format is "YYYY:MM:DD HH:MM:SS"
            if len(dt_str) >= 19:
                try:
                    dt_obj = datetime.strptime(dt_str[:19], "%Y:%m:%d %H:%M:%S")
                    return dt_obj.isoformat()
                except Exception:
                    # If parsing fails, fall through and return empty string
                    pass
    except Exception:
        return ""
    return ""


def compute_phash(path: str) -> str:
    """Compute perceptual hash for an image.  Returns hex string or '' on error."""
    try:
        with Image.open(path) as img:
            # Convert to RGB to avoid issues with modes like CMYK or grayscale
            ph = imagehash.average_hash(img.convert("RGB"))
            return ph.__str__()
    except Exception:
        return ""


def get_image_size(path: str) -> tuple:
    """Return (width, height) of an image or ('','') on failure."""
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return "", ""


def scan_directory(input_dir: str, output_csv: str) -> None:
    """Walk through input_dir and write metadata to output_csv."""
    entries = []
    for root, dirs, files in os.walk(input_dir):
        # Skip Photos libraries or backup directories
        for skip in [".photoslibrary", ".photolibrary", "Original_Backup_勿动"]:
            dirs[:] = [d for d in dirs if not d.endswith(skip)]
        for name in files:
            ext = name.rsplit(".", 1)[-1].lower()
            # only process known media types
            if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                continue
            full_path = os.path.join(root, name)
            try:
                stat = os.stat(full_path)
            except OSError:
                continue
            size_bytes = stat.st_size
            sha256 = compute_sha256(full_path)
            # mtime
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
            # EXIF datetime
            exif_dt = ""
            width = ""
            height = ""
            phash = ""
            if ext in IMAGE_EXTS:
                exif_dt = get_exif_datetime(full_path)
                width, height = get_image_size(full_path)
                phash = compute_phash(full_path)
                media_type = "image"
            else:
                media_type = "video"
            is_screenshot = (
                "screenshot" in name.lower() or "截图" in name.lower() or "截屏" in name.lower()
            )
            entries.append({
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
                "is_screenshot": str(is_screenshot),
            })
    # Write CSV
    fieldnames = [
        "file_path", "filename", "extension", "size_bytes", "sha256",
        "exif_datetime", "file_mtime", "width", "height", "phash",
        "media_type", "is_screenshot",
    ]
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in entries:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan photos/videos and build index")
    parser.add_argument("--input", required=True, help="Directory to scan")
    parser.add_argument("--output", required=True, help="Path to output CSV")
    args = parser.parse_args()
    input_dir = os.path.abspath(args.input)
    output_csv = os.path.abspath(args.output)
    if not os.path.isdir(input_dir):
        print(f"Error: {input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    scan_directory(input_dir, output_csv)
    print(f"Index written to {output_csv}")


if __name__ == "__main__":
    main()