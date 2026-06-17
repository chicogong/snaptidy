#!/usr/bin/env python3
"""Detect corrupted/broken images and videos in a photo index.

Checks each file for integrity:
  - Images: Pillow verify() + load() for truncated/corrupted detection
  - Videos: ffmpeg probe for playable check
  - Common: 0-byte file check, file existence check

Results written to DB columns: is_corrupted, corruption_type, corruption_detail

Usage:
  python detect_corrupted.py --index photo_index.db [--report corrupted.csv] [--parallel 4] [--incremental]
"""

import argparse
import csv
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


def check_file_exists(file_path: str) -> tuple:
    """Check if file exists and is non-zero. Returns (ok, type, detail)."""
    if not os.path.exists(file_path):
        return False, "missing", "File does not exist"
    if os.path.getsize(file_path) == 0:
        return False, "empty", "File is 0 bytes"
    return True, None, None


def check_image_corrupted(file_path: str) -> tuple:
    """Layered image integrity check.

    Returns (is_ok, corruption_type, corruption_detail).
    Layers: Pillow verify() → Pillow load() (catches truncated images).
    """
    # Try Pillow verify first (fast, catches most structural issues)
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        # No Pillow — try basic magic number check
        return _check_magic_number(file_path)

    # Layer 1: Image.open + verify() (fast, ~100x faster than load)
    try:
        with Image.open(file_path) as img:
            img.verify()
    except UnidentifiedImageError:
        return False, "unidentified", "Pillow cannot identify image format"
    except SyntaxError as e:
        return False, "syntax_error", str(e)[:200]
    except OSError as e:
        err = str(e).lower()
        if "truncated" in err:
            return False, "truncated", str(e)[:200]
        if "cannot identify" in err:
            return False, "unidentified", str(e)[:200]
        return False, "os_error", str(e)[:200]
    except Exception as e:
        return False, "verify_error", str(e)[:200]

    # Layer 2: Full load (catches truncated images that pass verify)
    try:
        with Image.open(file_path) as img:
            img.load()
    except OSError as e:
        err = str(e).lower()
        if "truncated" in err:
            return False, "truncated", str(e)[:200]
        if "broken" in err:
            return False, "broken_data", str(e)[:200]
        # Some images load with warnings but are still usable
        return True, None, None
    except Exception as e:
        # If verify passed but load failed, likely truncated
        return False, "load_error", str(e)[:200]

    return True, None, None


def _check_magic_number(file_path: str) -> tuple:
    """Basic magic number check when Pillow is unavailable."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(12)

        ext = Path(file_path).suffix.lower()
        if ext in (".jpg", ".jpeg"):
            if not header.startswith(b"\xff\xd8\xff"):
                return False, "bad_header", "JPEG magic number mismatch"
        elif ext == ".png":
            if not header.startswith(b"\x89PNG\r\n\x1a\n"):
                return False, "bad_header", "PNG magic number mismatch"
        elif ext == ".gif":
            if not (header.startswith(b"GIF87a") or header.startswith(b"GIF89a")):
                return False, "bad_header", "GIF magic number mismatch"
        elif ext == ".bmp":
            if not header.startswith(b"BM"):
                return False, "bad_header", "BMP magic number mismatch"

        return True, None, None
    except Exception as e:
        return False, "read_error", str(e)[:200]


def check_video_corrupted(file_path: str) -> tuple:
    """Check video integrity using ffmpeg probe.

    Returns (is_ok, corruption_type, corruption_detail).
    """
    try:
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0",
             file_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            err = result.stderr.strip()[:200] if result.stderr else "ffprobe error"
            return False, "probe_error", err

        # If probe succeeded but no video stream found
        if not result.stdout.strip():
            return False, "no_stream", "No video stream found"

        return True, None, None
    except FileNotFoundError:
        # ffmpeg not installed — skip video check
        return True, "ffmpeg_missing", "ffmpeg not installed, skipping video check"
    except subprocess.TimeoutExpired:
        return False, "timeout", "ffprobe timed out (possible corrupted file)"
    except Exception as e:
        return False, "probe_error", str(e)[:200]


def check_file(file_path: str, ext: str) -> dict:
    """Check a single file for corruption. Returns result dict."""
    result = {
        "file_path": file_path,
        "is_corrupted": False,
        "corruption_type": "",
        "corruption_detail": "",
    }

    # Step 1: Existence + size check
    ok, ctype, detail = check_file_exists(file_path)
    if not ok:
        result["is_corrupted"] = True
        result["corruption_type"] = ctype
        result["corruption_detail"] = detail
        return result

    # Step 2: Format-specific check
    ext_lower = ext.lower().lstrip(".") if ext else Path(file_path).suffix.lower().lstrip(".")
    ext_with_dot = f".{ext_lower}" if ext_lower else ""
    if ext_with_dot in IMAGE_EXTENSIONS:
        ok, ctype, detail = check_image_corrupted(file_path)
    elif ext_with_dot in VIDEO_EXTENSIONS:
        ok, ctype, detail = check_video_corrupted(file_path)
    else:
        # Unknown format — skip
        return result

    if not ok:
        result["is_corrupted"] = True
        result["corruption_type"] = ctype
        result["corruption_detail"] = detail

    return result


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def ensure_columns(conn):
    """Add corruption columns if they don't exist."""
    for col, dtype in [
        ("is_corrupted", "INTEGER DEFAULT 0"),
        ("corruption_type", "TEXT DEFAULT ''"),
        ("corruption_detail", "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col} {dtype}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.commit()


def get_files_to_check(index_path: str, incremental: bool = False) -> list:
    """Get list of files to check from index DB."""
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    if incremental:
        # Only check files not yet checked
        rows = conn.execute(
            "SELECT file_path, extension FROM photos "
            "WHERE is_corrupted IS NULL OR is_corrupted = 0"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT file_path, extension FROM photos"
        ).fetchall()

    conn.close()
    return [(r["file_path"], r["extension"] or "") for r in rows]


def write_results(index_path: str, results: list):
    """Write corruption check results to DB."""
    conn = sqlite3.connect(index_path)
    ensure_columns(conn)

    for r in results:
        conn.execute(
            "UPDATE photos SET is_corrupted=?, corruption_type=?, corruption_detail=? "
            "WHERE file_path=?",
            (int(r["is_corrupted"]), r["corruption_type"], r["corruption_detail"],
             r["file_path"]),
        )

    conn.commit()
    conn.close()


def write_report(results: list, report_path: str):
    """Write corrupted files report to CSV."""
    corrupted = [r for r in results if r["is_corrupted"]]
    if not corrupted:
        print(f"  No corrupted files found — skipping report")
        return

    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["file_path", "corruption_type", "corruption_detail"])
        writer.writeheader()
        writer.writerows(corrupted)

    print(f"  Corrupted files report → {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detect corrupted/broken images and videos in photo index",
    )
    parser.add_argument("--index", "-i", required=True, help="Path to SQLite index DB")
    parser.add_argument("--report", "-o", default="", help="Output CSV report for corrupted files")
    parser.add_argument("--parallel", "-p", type=int, default=4,
                        help="Number of parallel workers (default: 4)")
    parser.add_argument("--incremental", action="store_true",
                        help="Only check files not yet verified")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index DB not found: {args.index}")
        sys.exit(1)

    print(f"🔍 Checking for corrupted files...")
    start = time.time()

    # Ensure columns exist
    conn = sqlite3.connect(args.index)
    ensure_columns(conn)
    conn.close()

    # Get files to check
    files = get_files_to_check(args.index, args.incremental)
    print(f"  Files to check: {len(files)}")

    if not files:
        print("  No files to check.")
        return

    # Check files in parallel
    results = []
    corrupted_count = 0
    checked_count = 0

    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = {
            executor.submit(check_file, fp, ext): fp
            for fp, ext in files
        }

        for future in as_completed(futures):
            checked_count += 1
            if checked_count % 500 == 0:
                print(f"  Progress: {checked_count}/{len(files)} checked, "
                      f"{corrupted_count} corrupted")

            result = future.result()
            results.append(result)
            if result["is_corrupted"]:
                corrupted_count += 1

    elapsed = time.time() - start

    # Write results to DB
    write_results(args.index, results)

    # Write report if requested
    if args.report:
        write_report(results, args.report)

    # Summary
    print(f"\n  ✅ Checked {checked_count} files in {elapsed:.1f}s "
          f"({checked_count / max(elapsed, 0.01):.0f} files/s)")
    print(f"  💥 Corrupted: {corrupted_count}")

    if corrupted_count > 0:
        # Breakdown by type
        type_counts = {}
        for r in results:
            if r["is_corrupted"]:
                ctype = r["corruption_type"]
                type_counts[ctype] = type_counts.get(ctype, 0) + 1

        print("  Breakdown:")
        for ctype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"    {ctype}: {count}")

    return corrupted_count


if __name__ == "__main__":
    sys.exit(main() or 0)
