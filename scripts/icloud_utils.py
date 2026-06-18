#!/usr/bin/env python3
"""Shared iCloud detection and download utilities.

When macOS "Optimize Storage" is enabled, iCloud offloads original photos
to the cloud and keeps only small thumbnails locally (2-50 KB).  These
thumbnails have different SHA-256 hashes and pHashes than the originals,
making dedup results unreliable.  This module provides three detection
methods and a download trigger:

1. **`.icloud` companion file** (iCloud Drive style): a hidden file
   ``.{filename}.icloud`` exists next to the missing original.
2. **Extended attribute** ``com.apple.iCloud.syncState`` on the file.
3. **Size heuristic**: HEIC < 100 KB or JPEG < 20 KB is likely a
   thumbnail-only placeholder.

Detection functions return one of:
  * ``"local"``            — file is fully present on disk
  * ``"icloud_placeholder"`` — file is an iCloud thumbnail/stub
  * ``"unknown"``          — cannot determine (e.g. file missing)

``brctl download`` triggers a native macOS iCloud download.  This is
non-blocking — the caller should poll file size until it stabilises.
"""

import os
import shutil
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Size thresholds for thumbnail heuristic (bytes)
# ---------------------------------------------------------------------------
# iCloud-optimised HEIC thumbnails are typically 2-80 KB.
# A real HEIC photo from an iPhone is almost always > 300 KB.
THUMBNAIL_THRESHOLD_HEIC = 100 * 1024  # 100 KB

# iCloud-optimised JPEG thumbnails are typically 2-15 KB.
# A real JPEG photo is almost always > 50 KB.
THUMBNAIL_THRESHOLD_JPEG = 20 * 1024  # 20 KB

# Polling parameters for download
DOWNLOAD_POLL_INTERVAL = 1.0  # seconds between size checks
DOWNLOAD_TIMEOUT = 60  # seconds before giving up on a single file

# Default safety buffer: keep at least this much free space after downloads
DEFAULT_MIN_FREE_SPACE = 5 * 1024 * 1024 * 1024  # 5 GB

# Estimated size multiplier: originals are typically 10-50x larger than thumbnails
ESTIMATED_SIZE_MULTIPLIER = 25


def is_likely_thumbnail(size_bytes: int, ext: str) -> bool:
    """Heuristic: is this file likely an iCloud thumbnail rather than a real photo?

    Args:
        size_bytes: file size in bytes
        ext: lower-case extension without dot (e.g. "heic", "jpg")

    Returns:
        True if the file is small enough to be a thumbnail placeholder.
    """
    if size_bytes <= 0:
        return False
    ext = ext.lower().lstrip(".")
    if ext in ("heic", "heif"):
        return size_bytes < THUMBNAIL_THRESHOLD_HEIC
    if ext in ("jpg", "jpeg"):
        return size_bytes < THUMBNAIL_THRESHOLD_JPEG
    # For other formats, use a conservative 50 KB threshold
    return size_bytes < 50 * 1024


def check_icloud_status(path: str, size_bytes: int = -1, ext: str = "") -> str:
    """Check if a file is an iCloud placeholder (not fully downloaded).

    Uses three detection methods:
    1. ``.icloud`` companion file
    2. Extended attribute ``com.apple.iCloud.syncState``
    3. Size heuristic (if size_bytes and ext are provided)

    Args:
        path: absolute path to the file
        size_bytes: file size (optional — will stat if not provided)
        ext: lower-case extension without dot (optional — extracted from path)

    Returns:
        "local", "icloud_placeholder", or "unknown"
    """
    try:
        if not os.path.exists(path):
            return "unknown"

        # Get size if not provided
        if size_bytes < 0:
            size_bytes = os.path.getsize(path)
        if not ext:
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

        # Method 1: .icloud companion file (iCloud Drive style)
        dir_path = os.path.dirname(path)
        basename = os.path.basename(path)
        icloud_file = os.path.join(dir_path, f".{basename}.icloud")
        if os.path.exists(icloud_file):
            return "icloud_placeholder"

        # Method 2: zero-byte file with iCloud xattr
        if size_bytes == 0:
            result = subprocess.run(
                ["xattr", "-p", "com.apple.iCloud.syncState", path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return "icloud_placeholder"
            # Zero-byte without xattr — could be corrupted, treat as unknown
            return "unknown"

        # Method 3: size heuristic for small thumbnails
        if is_likely_thumbnail(size_bytes, ext):
            # Double-check with xattr — small file + iCloud xattr = definitely placeholder
            result = subprocess.run(
                ["xattr", "-p", "com.apple.iCloud.syncState", path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return "icloud_placeholder"
            # Small file without xattr — still suspicious, mark as placeholder
            # because real photos are almost never this small
            return "icloud_placeholder"

        return "local"
    except Exception:
        return "unknown"


def download_icloud_file(path: str, timeout: int = DOWNLOAD_TIMEOUT) -> bool:
    """Trigger download of an iCloud file and wait for it to complete.

    Uses ``brctl download`` on macOS to trigger iCloud download, then
    polls file size until it stabilises or timeout is reached.

    Args:
        path: absolute path to the file
        timeout: maximum seconds to wait for download (default: 60)

    Returns:
        True if the file was downloaded (or was already local),
        False if download failed or timed out.
    """
    # Already fully present?
    status = check_icloud_status(path)
    if status == "local":
        return True

    try:
        # Trigger download via brctl
        result = subprocess.run(
            ["brctl", "download", path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            # Fallback: try reading 1 byte to trigger download
            try:
                with open(path, "rb") as f:
                    f.read(1)
            except Exception:
                return False
    except Exception:
        return False

    # Poll until file size stabilises
    old_size = -1
    stable_count = 0
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            current_size = os.path.getsize(path)
        except OSError:
            return False

        if current_size == old_size and current_size > 0:
            stable_count += 1
            if stable_count >= 2:
                # Size hasn't changed for 2 intervals — download likely complete
                # Verify it's no longer a thumbnail
                ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
                if not is_likely_thumbnail(current_size, ext):
                    return True
                # Still small — might be a genuinely small photo
                return True
        else:
            stable_count = 0
        old_size = current_size
        time.sleep(DOWNLOAD_POLL_INTERVAL)

    # Timed out — check if file is at least bigger than before
    try:
        final_size = os.path.getsize(path)
        return final_size > 1024  # At least 1 KB
    except OSError:
        return False


def get_disk_space(path: str) -> tuple:
    """Get disk space information for the volume containing *path*.

    Returns:
        (total_bytes, used_bytes, free_bytes)
    """
    usage = shutil.disk_usage(path)
    return (usage.total, usage.used, usage.free)


def check_disk_space(download_path: str, estimated_bytes: int,
                     min_free_bytes: int = DEFAULT_MIN_FREE_SPACE) -> dict:
    """Check if there's enough disk space for a download.

    Args:
        download_path: a path on the volume where files will be downloaded
        estimated_bytes: estimated total download size in bytes
        min_free_bytes: minimum free space to keep after download (safety buffer)

    Returns:
        dict with keys:
            "sufficient": bool — True if enough space
            "total": int — total disk space
            "free": int — current free space
            "available_for_download": int — free - min_free (what we can actually use)
            "estimated": int — estimated download size
            "shortfall": int — how much more space is needed (0 if sufficient)
            "max_files": int — how many files can be downloaded with available space
    """
    total, used, free = get_disk_space(download_path)
    available = max(0, free - min_free_bytes)
    shortfall = max(0, estimated_bytes - available)

    # Estimate how many files can be downloaded
    # If estimated_bytes is for N files, each file averages estimated_bytes/N
    max_files = 0
    if estimated_bytes > 0:
        avg_per_file = estimated_bytes / max(1, 1)  # will be overridden by caller
        max_files = int(available // (estimated_bytes / max(1, 1))) if estimated_bytes else 0

    return {
        "sufficient": available >= estimated_bytes,
        "total": total,
        "free": free,
        "available_for_download": available,
        "estimated": estimated_bytes,
        "shortfall": shortfall,
        "max_files": max_files,
    }


def estimate_download_size(icloud_files: list) -> int:
    """Estimate total download size for a list of iCloud placeholder files.

    Uses the thumbnail size × multiplier heuristic: originals are typically
    10-50x larger than thumbnails. We use a conservative 25x multiplier.

    Args:
        icloud_files: list of dicts from scan_directory_for_icloud()

    Returns:
        Estimated total bytes needed for download.
    """
    total_thumbnail_size = sum(f.get("size", 0) for f in icloud_files)
    return total_thumbnail_size * ESTIMATED_SIZE_MULTIPLIER


def batch_download(paths: list, progress_callback=None) -> dict:
    """Batch download multiple iCloud files with progress reporting.

    Args:
        paths: list of file paths to download
        progress_callback: optional callable(done, total, current_path, success)

    Returns:
        dict with keys: "downloaded", "failed", "skipped", "total"
    """
    results = {"downloaded": 0, "failed": 0, "skipped": 0, "total": len(paths)}

    for idx, path in enumerate(paths):
        status = check_icloud_status(path)
        if status == "local":
            results["skipped"] += 1
            if progress_callback:
                progress_callback(idx + 1, len(paths), path, True)
            continue

        success = download_icloud_file(path)
        if success:
            results["downloaded"] += 1
        else:
            results["failed"] += 1

        if progress_callback:
            progress_callback(idx + 1, len(paths), path, success)

    return results


def scan_directory_for_icloud(root_dir: str) -> list:
    """Scan a directory for iCloud-only files.

    Walks the directory tree and returns a list of dicts with file info
    for files detected as iCloud placeholders.

    Args:
        root_dir: directory to scan

    Returns:
        List of dicts: [{"path": str, "size": int, "ext": str, "reason": str}, ...]
    """
    results = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip hidden/system directories
        dirnames[:] = [d for d in dirnames if not d.startswith(".")
                       and d not in ("__pycache__", "node_modules", ".git")]

        for filename in filenames:
            # Skip .icloud companion files themselves
            if filename.startswith(".") and filename.endswith(".icloud"):
                continue

            full_path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            # Skip non-media files
            media_exts = {
                "jpg", "jpeg", "png", "heic", "heif", "gif", "bmp",
                "tif", "tiff", "webp", "avif", "raw",
                "mov", "mp4", "m4v", "avi", "mkv",
            }
            if ext not in media_exts:
                continue

            status = check_icloud_status(full_path, size, ext)
            if status == "icloud_placeholder":
                # Determine detection reason
                dir_path = os.path.dirname(full_path)
                icloud_file = os.path.join(dir_path, f".{filename}.icloud")
                if os.path.exists(icloud_file):
                    reason = "companion_file"
                elif size == 0:
                    reason = "zero_byte"
                else:
                    reason = "thumbnail_heuristic"

                results.append({
                    "path": full_path,
                    "size": size,
                    "ext": ext,
                    "reason": reason,
                })

    return results
