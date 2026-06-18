#!/usr/bin/env python3
"""Detect files whose content (magic bytes) doesn't match their extension.

Reads the metadata index (SQLite DB) and checks each file's actual format
via magic-byte signatures against its declared extension. Mismatches often
indicate accidentally renamed files, corrupted downloads, or disguised files.

Results are written back to the DB (new columns) and/or exported as CSV/JSON.

DB columns added:
  bad_extension    — 0 (ok) or 1 (mismatch)
  actual_format    — detected format from magic bytes (e.g. "jpeg", "png")
  declared_format  — format from extension (e.g. "heic", "jpg")

Usage:
  # Check all files and write results to DB
  python3 scripts/detect_bad_extensions.py --index photo_index.db

  # Also export a CSV report
  python3 scripts/detect_bad_extensions.py --index photo_index.db --report bad_extensions.csv

  # Only check files not yet checked (incremental)
  python3 scripts/detect_bad_extensions.py --index photo_index.db --incremental

  # Parallel processing for large libraries
  python3 scripts/detect_bad_extensions.py --index photo_index.db --parallel 4
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from constants import IMAGE_EXTS, VIDEO_EXTS, RAW_EXTS


# ---------------------------------------------------------------------------
# Magic byte signatures — maps file header patterns to actual format
# ---------------------------------------------------------------------------

# Each entry: (offset, expected_bytes, format_name, extension_set)
# extension_set is the set of valid extensions for this format
MAGIC_SIGNATURES = [
    # JPEG: FF D8 FF
    (0, b"\xff\xd8\xff", "jpeg", {"jpg", "jpeg"}),
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    (0, b"\x89PNG\r\n\x1a\n", "png", {"png"}),
    # GIF: GIF87a or GIF89a
    (0, b"GIF87a", "gif", {"gif"}),
    (0, b"GIF89a", "gif", {"gif"}),
    # BMP: BM
    (0, b"BM", "bmp", {"bmp"}),
    # TIFF: little-endian (II*\x00) or big-endian (MM\x00*)
    (0, b"II*\x00", "tiff", {"tif", "tiff"}),
    (0, b"MM\x00*", "tiff", {"tif", "tiff"}),
    # WebP: RIFF....WEBP
    (0, b"RIFF", "webp", {"webp"}),
    # HEIC/HEIF: ftyp box with heic/heix/mif1/msf1 brand
    (4, b"heic", "heic", {"heic", "heif"}),
    (4, b"heix", "heic", {"heic", "heif"}),
    (4, b"mif1", "heif", {"heic", "heif"}),
    (4, b"msf1", "heif", {"heic", "heif"}),
    # AVIF: ftyp box with avif/avis brand
    (4, b"avif", "avif", {"avif"}),
    (4, b"avis", "avif", {"avif"}),
    # AVI: RIFF....AVI
    (8, b"AVI ", "avi", {"avi"}),
    # MP4/MOV: ftyp box
    (4, b"ftyp", "mp4", {"mp4", "m4v", "mov"}),
    # MKV/WebM: EBML header
    (0, b"\x1aE\xdf\xa3", "mkv", {"mkv", "webm", "m2ts"}),
    # WMV/ASF: ASF header GUID
    (0, b"\x30\x26\xb2\x75", "wmv", {"wmv", "asf"}),
    # FLV: FLV header
    (0, b"FLV", "flv", {"flv"}),
    # 3GP: ftyp with 3gp brand
    (8, b"3gp", "3gp", {"3gp"}),
    # MPEG: MPEG transport stream
    (0, b"\x00\x00\x01", "mpeg", {"mpg", "mpeg", "mts"}),
    # PPM/PBM/PGM: P6/P5/P4 magic
    (0, b"P6", "ppm", {"ppm"}),
    (0, b"P5", "pgm", {"pgm"}),
    (0, b"P4", "pbm", {"pbm"}),
    # ICO: 00 00 01 00
    (0, b"\x00\x00\x01\x00", "ico", {"ico"}),
]

# RAW formats that need longer headers for detection
RAW_SIGNATURES = [
    # CR2: TIFF with CR2 tag (II + offset to IFD0 at byte 8, then CR2 at byte 9-10)
    # CR2 is TIFF-based, detect by checking for "CR" at offset 8-9
    (8, b"CR", "cr2", {"cr2"}),
    # ORF: Olympus ORF (IIRO or MMOR)
    (0, b"IIRO", "orf", {"orf"}),
    (0, b"MMOR", "orf", {"orf"}),
    # RW2: Panasonic (IIU\x00)
    (0, b"IIU\x00", "rw2", {"rw2"}),
    # RAF: Fujifilm ("FUJIFILMCCD-RAW")
    (0, b"FUJIFILMCCD-RAW", "raf", {"raf"}),
    # ARW: Sony (TIFF-based with Sony tag)
    # ARW is TIFF-based, so it starts with II* — we detect it by checking
    # for Sony-specific maker note tag (hard to detect reliably, so we
    # accept TIFF header as valid for ARW/CR2/NEF/DNG/SRW)
    # NEF: Nikon (TIFF-based, starts with II* or MM*)
    # DNG: Adobe Digital Negative (TIFF-based)
    # SRW: Samsung (TIFF-based)
    # These are all TIFF-based, so they match the TIFF signature above.
    # We accept any TIFF-based extension as valid for TIFF headers.
]

# All signatures combined
ALL_SIGNATURES = MAGIC_SIGNATURES + RAW_SIGNATURES

# Minimum header bytes to read
MIN_HEADER_SIZE = 16

# Extensions that are TIFF-based (accept TIFF header as valid)
TIFF_BASED_EXTS = {"tif", "tiff", "cr2", "nef", "arw", "dng", "srw", "raw"}


def detect_format_from_header(file_path: str) -> tuple:
    """Read file magic bytes and detect actual format.

    Returns (actual_format, is_confident).
    actual_format is None if format couldn't be determined.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(MIN_HEADER_SIZE)
    except Exception:
        return None, False

    if len(header) < 4:
        return None, False

    # Check all signatures
    for offset, expected, fmt_name, valid_exts in ALL_SIGNATURES:
        end = offset + len(expected)
        if len(header) >= end and header[offset:end] == expected:
            # Special case: RIFF could be WebP or AVI
            if expected == b"RIFF":
                # Check bytes 8-12 for WEBP or AVI
                if len(header) >= 12:
                    if header[8:12] == b"WEBP":
                        return "webp", True
                    elif header[8:12] == b"AVI ":
                        return "avi", True
                return None, False
            # Special case: ftyp box could be MP4/MOV/HEIC/AVIF
            if expected == b"ftyp":
                if len(header) >= 12:
                    brand = header[8:12]
                    if brand in (b"heic", b"heix", b"mif1", b"msf1"):
                        return "heic", True
                    elif brand in (b"avif", b"avis"):
                        return "avif", True
                    elif brand in (b"qt  ", b"mp42", b"isom", b"iso2", b"mp41", b"mmp4"):
                        return "mp4", True
                return "mp4", True  # ftyp = some MPEG container
            return fmt_name, True

    # Check for MPEG transport stream (starts with 0x47 sync byte)
    if len(header) >= 1 and header[0] == 0x47:
        return "mpeg", True

    return None, False


def check_bad_extension(file_path: str, declared_ext: str) -> dict:
    """Check if file content matches its extension.

    Returns dict with:
      bad_extension: True if mismatch detected
      actual_format: format detected from magic bytes
      declared_format: format from extension
    """
    ext_lower = declared_ext.lower().lstrip(".")

    # Detect actual format from magic bytes
    actual_format, confident = detect_format_from_header(file_path)

    result = {
        "file_path": file_path,
        "bad_extension": False,
        "actual_format": actual_format if actual_format else "",
        "declared_format": ext_lower,
    }

    if not confident or not actual_format:
        # Can't determine — skip (not necessarily bad)
        return result

    # Check if actual format matches declared extension
    # Special: TIFF-based RAWs (CR2, NEF, ARW, DNG, SRW) all start with TIFF header
    if actual_format == "tiff" and ext_lower in TIFF_BASED_EXTS:
        # Valid — these are all TIFF-based formats
        result["actual_format"] = ext_lower  # Trust the extension for RAW
        return result

    # Find valid extensions for the detected format
    valid_exts = set()
    for _, _, fmt_name, ext_set in ALL_SIGNATURES:
        if fmt_name == actual_format:
            valid_exts |= ext_set

    # Also add format family aliases
    if actual_format == "jpeg":
        valid_exts |= {"jpg", "jpeg"}
    elif actual_format == "tiff":
        valid_exts |= TIFF_BASED_EXTS
    elif actual_format == "heic":
        valid_exts |= {"heic", "heif"}
    elif actual_format == "mp4":
        valid_exts |= {"mp4", "m4v", "mov"}

    if ext_lower not in valid_exts:
        result["bad_extension"] = True
        # Don't flag non-media extensions as bad (could be sidecar files etc.)
        if ext_lower not in IMAGE_EXTS and ext_lower not in VIDEO_EXTS and ext_lower not in RAW_EXTS:
            result["bad_extension"] = False

    return result


# ---------------------------------------------------------------------------
# DB schema migration
# ---------------------------------------------------------------------------

BAD_EXT_COLUMNS = [
    ("bad_extension", "INTEGER DEFAULT 0"),
    ("actual_format", "TEXT DEFAULT ''"),
    ("declared_format", "TEXT DEFAULT ''"),
]


def migrate_db(conn: sqlite3.Connection) -> None:
    """Add bad extension columns to photos table if they don't exist."""
    for col_name, col_type in BAD_EXT_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bad_ext ON photos(bad_extension)")
    except sqlite3.OperationalError:
        pass

    conn.commit()


# ---------------------------------------------------------------------------
# Main detection logic
# ---------------------------------------------------------------------------

def detect_bad_extensions(index_path: str, incremental: bool = False,
                          report_path: str = None, parallel: int = 1) -> dict:
    """Detect bad extensions for all files in the index.

    Args:
        index_path: Path to SQLite index DB.
        incremental: If True, only check files not yet checked.
        report_path: If set, also write a report file (csv/json).

    Returns:
        Summary dict with counts and stats.
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    migrate_db(conn)

    # Build query
    query = """
        SELECT file_path, filename, extension
        FROM photos
    """
    if incremental:
        query += " WHERE bad_extension IS NULL OR bad_extension = 0 AND actual_format = ''"

    cursor = conn.execute(query)
    rows = cursor.fetchall()

    total = len(rows)
    if total == 0:
        print("No files to check.")
        conn.close()
        return {"total": 0, "checked": 0, "mismatches": 0}

    print(f"Checking extensions for {total} files (parallel={parallel})...")

    checked = 0
    mismatches = 0
    errors = 0
    report_rows = []
    last_pct = -1

    if parallel <= 1:
        for idx, row in enumerate(rows):
            pct = idx * 100 // total
            if pct >= last_pct + 5 or idx == 0:
                print(f"  Checking... {idx}/{total} ({pct}%)")
                last_pct = pct

            file_path = row["file_path"]
            ext = (row["extension"] or "").lower().lstrip(".")

            if not os.path.exists(file_path):
                errors += 1
                continue

            result = check_bad_extension(file_path, ext)

            conn.execute(
                "UPDATE photos SET bad_extension = ?, actual_format = ?, declared_format = ? "
                "WHERE file_path = ?",
                (int(result["bad_extension"]), result["actual_format"],
                 result["declared_format"], file_path),
            )
            conn.commit()
            checked += 1

            if result["bad_extension"]:
                mismatches += 1

            if report_path:
                report_rows.append({
                    "file_path": file_path,
                    "filename": row["filename"] or "",
                    "declared_extension": ext,
                    "actual_format": result["actual_format"],
                    "declared_format": result["declared_format"],
                    "bad_extension": "YES" if result["bad_extension"] else "NO",
                })
    else:
        tasks = []
        for row in rows:
            file_path = row["file_path"]
            ext = (row["extension"] or "").lower().lstrip(".")
            if not os.path.exists(file_path):
                errors += 1
                continue
            tasks.append((file_path, ext, row))

        done_count = 0
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            future_to_data = {
                executor.submit(check_bad_extension, fp, ext): (fp, ext, row)
                for fp, ext, row in tasks
            }
            for future in as_completed(future_to_data):
                done_count += 1
                pct = done_count * 100 // len(tasks)
                if pct >= last_pct + 5 or done_count == 1:
                    print(f"  Checking... {done_count}/{len(tasks)} ({pct}%)")
                    last_pct = pct

                fp, ext, row = future_to_data[future]
                try:
                    result = future.result()
                except Exception:
                    errors += 1
                    continue

                conn.execute(
                    "UPDATE photos SET bad_extension = ?, actual_format = ?, declared_format = ? "
                    "WHERE file_path = ?",
                    (int(result["bad_extension"]), result["actual_format"],
                     result["declared_format"], fp),
                )
                checked += 1

                if result["bad_extension"]:
                    mismatches += 1

                if report_path:
                    report_rows.append({
                        "file_path": fp,
                        "filename": row["filename"] or "",
                        "declared_extension": ext,
                        "actual_format": result["actual_format"],
                        "declared_format": result["declared_format"],
                        "bad_extension": "YES" if result["bad_extension"] else "NO",
                    })

        conn.commit()

    conn.close()

    if report_path and report_rows:
        _write_report(report_rows, report_path)

    summary = {
        "total": total,
        "checked": checked,
        "mismatches": mismatches,
        "errors": errors,
    }

    return summary


def _write_report(rows: list, path: str) -> None:
    """Write bad extension report to CSV or JSON."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "csv"

    if ext == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
    else:
        fieldnames = [
            "file_path", "filename", "declared_extension",
            "actual_format", "declared_format", "bad_extension",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    print(f"  Report written: {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect files whose content (magic bytes) doesn't match their extension")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index (from scan_photos.py)")
    parser.add_argument("--report", "-r", dest="report", default="",
                        help="Also export a report (.csv or .json)")
    parser.add_argument("--incremental", action="store_true",
                        help="Only check files not yet checked")
    parser.add_argument("--parallel", "-p", type=int, default=1,
                        help="Number of parallel workers (default: 1, try 4 for speed)")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    summary = detect_bad_extensions(
        os.path.abspath(args.index),
        incremental=args.incremental,
        report_path=os.path.abspath(args.report) if args.report else None,
        parallel=args.parallel,
    )

    print(f"\n{'=' * 50}")
    print(f"Bad Extension Detection Complete")
    print(f"  Files checked:    {summary['total']}")
    print(f"  Successfully:      {summary['checked']}")
    if summary['errors'] > 0:
        print(f"  Errors (skipped): {summary['errors']}")
    print(f"  Mismatches found: {summary['mismatches']}")
    if summary['mismatches'] > 0:
        print(f"\n  Tip: Use --report bad_extensions.csv for details")
    print(f"\n  Results written to: {args.index}")
    print(f"  Columns added: bad_extension, actual_format, declared_format")


if __name__ == "__main__":
    main()
