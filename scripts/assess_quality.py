#!/usr/bin/env python3
"""Assess photo quality — blur, brightness, contrast, and overall quality score.

Reads the metadata index (SQLite DB) and computes quality metrics for each
image file. Results are written back to the DB (new columns) and/or exported
as a standalone CSV/JSON report.

Quality metrics:
  blur_score     — Laplacian variance (lower = more blurry). 0-1000+ scale.
                   Typical: sharp >100, acceptable 50-100, blurry <50
  brightness     — Mean pixel intensity (0-255). Dark <60, normal 60-180, bright >180
  contrast       — Standard deviation of pixel intensity (0-128).
                   Flat <30, normal 30-70, high-contrast >70
  quality_score  — Composite 0-100 score (higher = better quality).
                   Formula: 40*sharpness + 25*exposure + 20*contrast + 15*resolution

Usage:
    # Assess all images and write scores to the index DB
    python3 scripts/assess_quality.py --index photo_index.db

    # Also export a CSV report
    python3 scripts/assess_quality.py --index photo_index.db --report quality_report.csv

    # JSON report
    python3 scripts/assess_quality.py --index photo_index.db --report quality_report.json

    # Only assess images without quality scores (incremental)
    python3 scripts/assess_quality.py --index photo_index.db --incremental

    # Include quality scores in dedup decisions
    python3 scripts/generate_move_plan.py --duplicates dupes.csv --index photo_index.db \
        --strategy quality  # now considers blur/brightness/contrast
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from photo_metadata import PILLOW_AVAILABLE
from constants import IMAGE_EXTS


# ---------------------------------------------------------------------------
# Quality metric computation
# ---------------------------------------------------------------------------

def compute_blur_score(img) -> float:
    """Compute blur score using Laplacian variance.

    Higher value = sharper image.  Typical thresholds:
      - < 30:  very blurry
      - 30-80: slightly blurry
      - 80-150: acceptable
      - > 150: sharp

    Returns the Laplacian variance as a float, or -1 on error.
    """
    if not PILLOW_AVAILABLE:
        return -1
    try:
        import numpy as np
        # Convert to grayscale
        gray = img.convert("L")
        arr = np.array(gray, dtype=np.float64)

        # Laplacian kernel (3x3)
        kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)

        # Apply convolution (manual, to avoid scipy dependency)
        h, w = arr.shape
        if h < 3 or w < 3:
            return -1

        # Pad array
        padded = np.pad(arr, 1, mode="edge")
        laplacian = np.zeros_like(arr)
        for i in range(h):
            for j in range(w):
                patch = padded[i:i + 3, j:j + 3]
                laplacian[i, j] = np.sum(patch * kernel)

        # Variance of Laplacian
        return float(np.var(laplacian))
    except ImportError:
        # Fallback: use PIL's built-in filter for a simpler blur metric
        return _blur_score_pil(img)
    except Exception:
        return -1


def _blur_score_pil(img) -> float:
    """Fallback blur score without numpy — uses PIL ImageFilter.

    Less precise but works without numpy.
    Returns a rough Laplacian variance estimate, or -1 on error.
    """
    try:
        from PIL import ImageFilter
        gray = img.convert("L")
        # Apply edge detection (approximation of Laplacian)
        edges = gray.filter(ImageFilter.FIND_EDGES)
        # Compute variance of edge intensities
        pixels = list(edges.getdata())
        n = len(pixels)
        if n == 0:
            return -1
        mean = sum(pixels) / n
        variance = sum((p - mean) ** 2 for p in pixels) / n
        return variance
    except Exception:
        return -1


def compute_brightness(img) -> float:
    """Compute mean brightness (0-255) from grayscale image.

    Returns -1 on error.
    """
    try:
        gray = img.convert("L")
        pixels = list(gray.get_flattened_data() if hasattr(gray, 'get_flattened_data') else gray.getdata())
        n = len(pixels)
        if n == 0:
            return -1
        return sum(pixels) / n
    except Exception:
        return -1


def compute_contrast(img) -> float:
    """Compute contrast as standard deviation of pixel intensity (0-128).

    Returns -1 on error.
    """
    try:
        gray = img.convert("L")
        pixels = list(gray.get_flattened_data() if hasattr(gray, 'get_flattened_data') else gray.getdata())
        n = len(pixels)
        if n == 0:
            return -1
        mean = sum(pixels) / n
        variance = sum((p - mean) ** 2 for p in pixels) / n
        return variance ** 0.5
    except Exception:
        return -1


def compute_quality_score(blur: float, brightness: float, contrast: float,
                          width: int = 0, height: int = 0,
                          fmt_family: str = "", file_size: int = 0,
                          has_exif_date: bool = False, has_gps: bool = False,
                          has_camera: bool = False) -> int:
    """Compute composite quality score (0-100) using multi-dimensional scoring.

    Components (7 dimensions):
      25% — Sharpness (blur score mapped to 0-25)
      15% — Exposure quality (brightness mapped to 0-15)
      10% — Contrast (contrast mapped to 0-10)
      15% — Resolution (pixel count mapped to 0-15)
      10% — Format quality (RAW > HEIC > JPEG > PNG > BMP)
      10% — File size efficiency (bytes per pixel, detects over/under-compressed)
      15% — EXIF completeness (date + GPS + camera presence)

    Returns integer 0-100.
    """
    score = 0.0

    # 1. Sharpness component (0-25)
    if blur >= 0:
        if blur < 30:
            sharp = 3 + (blur / 30) * 7
        elif blur < 80:
            sharp = 10 + ((blur - 30) / 50) * 8
        elif blur < 200:
            sharp = 18 + ((blur - 80) / 120) * 5
        else:
            sharp = 23 + min((blur - 200) / 500, 1) * 2
        score += min(sharp, 25)
    else:
        score += 12  # Unknown, give average

    # 2. Exposure component (0-15)
    if brightness >= 0:
        if 80 <= brightness <= 140:
            exposure = 15
        elif 60 <= brightness < 80:
            exposure = 9 + ((brightness - 60) / 20) * 6
        elif 140 < brightness <= 180:
            exposure = 15 - ((brightness - 140) / 40) * 6
        elif brightness < 60:
            exposure = max(0, (brightness / 60) * 9)
        else:
            exposure = max(0, 9 - ((brightness - 180) / 75) * 9)
        score += min(exposure, 15)
    else:
        score += 7

    # 3. Contrast component (0-10)
    if contrast >= 0:
        if 40 <= contrast <= 80:
            cont = 10
        elif 25 <= contrast < 40:
            cont = 6 + ((contrast - 25) / 15) * 4
        elif 80 < contrast <= 100:
            cont = 10 - ((contrast - 80) / 20) * 3
        elif contrast < 25:
            cont = max(0, (contrast / 25) * 6)
        else:
            cont = max(0, 7 - ((contrast - 100) / 28) * 7)
        score += min(cont, 10)
    else:
        score += 5

    # 4. Resolution component (0-15)
    pixels = width * height
    if pixels > 0:
        mp = pixels / 1_000_000
        if mp < 1:
            res = 3
        elif mp < 8:
            res = 6 + ((mp - 1) / 7) * 4
        elif mp < 20:
            res = 10 + ((mp - 8) / 12) * 4
        else:
            res = 14 + min((mp - 20) / 30, 1) * 1
        score += min(res, 15)
    else:
        score += 7

    # 5. Format quality component (0-10)
    # RAW > HEIC > AVIF > JPEG > TIFF > WebP > PNG > BMP > Other
    format_scores = {
        "raw": 10, "heic": 9, "avif": 8, "jpeg": 7,
        "tiff": 6, "webp": 5, "png": 4, "bmp": 2,
        "gif": 3, "ico": 1,
    }
    fmt_lower = (fmt_family or "").lower()
    score += format_scores.get(fmt_lower, 3)

    # 6. File size efficiency component (0-10)
    # Bytes per pixel: ideal range detects well-compressed but not over-compressed
    if pixels > 0 and file_size > 0:
        bpp = file_size / pixels  # bytes per pixel
        if bpp < 0.1:
            # Very low — possibly over-compressed or tiny
            fs = 4
        elif bpp < 0.5:
            # Good compression (HEIC, AVIF range)
            fs = 10
        elif bpp < 2.0:
            # Normal JPEG range
            fs = 8
        elif bpp < 5.0:
            # Uncompressed-ish (PNG, BMP)
            fs = 6
        elif bpp < 15.0:
            # RAW territory
            fs = 7
        else:
            # Very large — possibly uncompressed TIFF or problematic
            fs = 4
        score += fs
    else:
        score += 5

    # 7. EXIF completeness component (0-15)
    exif_score = 0
    if has_exif_date:
        exif_score += 6  # Date is most important
    if has_gps:
        exif_score += 4  # GPS is valuable
    if has_camera:
        exif_score += 5  # Camera info is useful
    score += exif_score

    return max(0, min(100, int(round(score))))


# ---------------------------------------------------------------------------
# DB schema migration
# ---------------------------------------------------------------------------

QUALITY_COLUMNS = [
    ("blur_score", "REAL DEFAULT -1"),
    ("brightness", "REAL DEFAULT -1"),
    ("contrast", "REAL DEFAULT -1"),
    ("quality_score", "INTEGER DEFAULT -1"),
    ("sharpness_score", "INTEGER DEFAULT -1"),
    ("exposure_score", "INTEGER DEFAULT -1"),
    ("contrast_score", "INTEGER DEFAULT -1"),
    ("resolution_score", "INTEGER DEFAULT -1"),
    ("format_score", "INTEGER DEFAULT -1"),
    ("filesize_score", "INTEGER DEFAULT -1"),
    ("exif_score", "INTEGER DEFAULT -1"),
]


def migrate_db(conn: sqlite3.Connection) -> None:
    """Add quality columns to photos table if they don't exist."""
    for col_name, col_type in QUALITY_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Index for quality-based queries
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_quality_score ON photos(quality_score)")
    except sqlite3.OperationalError:
        pass

    conn.commit()


# ---------------------------------------------------------------------------
# Single-file quality assessment (callable from thread pool)
# ---------------------------------------------------------------------------

def _compute_dimension_scores(blur, brightness, contrast, width, height,
                               fmt_family, file_size, has_exif_date, has_gps, has_camera):
    """Compute individual dimension scores (0-100 each)."""
    # Sharpness dimension (0-100)
    if blur >= 0:
        if blur < 30:
            sharp = 15 + (blur / 30) * 35
        elif blur < 80:
            sharp = 50 + ((blur - 30) / 50) * 30
        elif blur < 200:
            sharp = 80 + ((blur - 80) / 120) * 15
        else:
            sharp = 95 + min((blur - 200) / 500, 1) * 5
        sharpness = min(100, int(round(sharp)))
    else:
        sharpness = 50

    # Exposure dimension (0-100)
    if brightness >= 0:
        if 80 <= brightness <= 140:
            exposure = 100
        elif 60 <= brightness < 80:
            exposure = 60 + ((brightness - 60) / 20) * 40
        elif 140 < brightness <= 180:
            exposure = 100 - ((brightness - 140) / 40) * 30
        elif brightness < 60:
            exposure = max(0, (brightness / 60) * 60)
        else:
            exposure = max(0, 60 - ((brightness - 180) / 75) * 60)
        exposure = min(100, int(round(exposure)))
    else:
        exposure = 50

    # Contrast dimension (0-100)
    if contrast >= 0:
        if 40 <= contrast <= 80:
            cont = 100
        elif 25 <= contrast < 40:
            cont = 60 + ((contrast - 25) / 15) * 40
        elif 80 < contrast <= 100:
            cont = 100 - ((contrast - 80) / 20) * 30
        elif contrast < 25:
            cont = max(0, (contrast / 25) * 60)
        else:
            cont = max(0, 70 - ((contrast - 100) / 28) * 70)
        contrast_dim = min(100, int(round(cont)))
    else:
        contrast_dim = 50

    # Resolution dimension (0-100)
    pixels = width * height
    if pixels > 0:
        mp = pixels / 1_000_000
        if mp < 1:
            res = 20
        elif mp < 8:
            res = 40 + ((mp - 1) / 7) * 30
        elif mp < 20:
            res = 70 + ((mp - 8) / 12) * 25
        else:
            res = 95 + min((mp - 20) / 30, 1) * 5
        resolution = min(100, int(round(res)))
    else:
        resolution = 50

    # Format dimension (0-100)
    format_map = {
        "raw": 100, "heic": 90, "avif": 85, "jpeg": 75,
        "tiff": 70, "webp": 60, "png": 50, "bmp": 25,
        "gif": 35, "ico": 10,
    }
    format_dim = format_map.get((fmt_family or "").lower(), 30)

    # File size efficiency dimension (0-100)
    if pixels > 0 and file_size > 0:
        bpp = file_size / pixels
        if bpp < 0.1:
            fs = 40
        elif bpp < 0.5:
            fs = 100
        elif bpp < 2.0:
            fs = 80
        elif bpp < 5.0:
            fs = 60
        elif bpp < 15.0:
            fs = 70
        else:
            fs = 40
        filesize = fs
    else:
        filesize = 50

    # EXIF completeness dimension (0-100)
    exif_dim = 0
    if has_exif_date:
        exif_dim += 40
    if has_gps:
        exif_dim += 25
    if has_camera:
        exif_dim += 35

    return {
        "sharpness_score": sharpness,
        "exposure_score": exposure,
        "contrast_score": contrast_dim,
        "resolution_score": resolution,
        "format_score": format_dim,
        "filesize_score": filesize,
        "exif_score": exif_dim,
    }


def _assess_one(file_path: str, ext: str, width: int, height: int,
                fmt_family: str = "", file_size: int = 0,
                has_exif_date: bool = False, has_gps: bool = False,
                has_camera: bool = False) -> dict | None:
    """Assess quality for a single image. Returns result dict or None on error."""
    from PIL import Image

    if ext not in IMAGE_EXTS:
        return None
    if not os.path.exists(file_path):
        return None

    try:
        with Image.open(file_path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            max_dim = 800
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.BILINEAR)

            blur = compute_blur_score(img)
            brightness = compute_brightness(img)
            contrast = compute_contrast(img)

            # Compute individual dimension scores
            dims = _compute_dimension_scores(
                blur, brightness, contrast, width, height,
                fmt_family, file_size, has_exif_date, has_gps, has_camera
            )

            # Compute composite quality score using weighted formula
            quality = compute_quality_score(
                blur, brightness, contrast, width, height,
                fmt_family, file_size, has_exif_date, has_gps, has_camera
            )

        return {
            "file_path": file_path,
            "blur_score": blur,
            "brightness": brightness,
            "contrast": contrast,
            "quality_score": quality,
            **dims,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main assessment logic
# ---------------------------------------------------------------------------

def assess_quality(index_path: str, incremental: bool = False,
                   report_path: str = None, parallel: int = 1) -> dict:
    """Assess quality for all images in the index.

    Args:
        index_path: Path to SQLite index DB.
        incremental: If True, only assess images without quality scores.
        report_path: If set, also write a report file (csv/json).

    Returns:
        Summary dict with counts and stats.
    """
    if not PILLOW_AVAILABLE:
        print("Error: Pillow is required for quality assessment.", file=sys.stderr)
        print("       Install with: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    from PIL import Image

    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    migrate_db(conn)

    # Build query — fetch columns needed for multi-dimensional scoring
    query = """
        SELECT file_path, filename, extension, width, height, category,
               size_bytes, exif_datetime, gps_latitude, camera_make
        FROM photos
        WHERE media_type = 'image'
    """
    if incremental:
        query += " AND quality_score = -1"

    cursor = conn.execute(query)
    rows = cursor.fetchall()

    total = len(rows)
    if total == 0:
        print("No images to assess.")
        conn.close()
        return {"total": 0, "assessed": 0}

    print(f"Assessing quality for {total} images (parallel={parallel})...")

    assessed = 0
    errors = 0
    report_rows = []
    last_pct = -1

    if parallel <= 1:
        # Sequential mode (original logic, for compatibility / debugging)
        for idx, row in enumerate(rows):
            pct = idx * 100 // total
            if pct >= last_pct + 5 or idx == 0:
                print(f"  Assessing... {idx}/{total} ({pct}%)")
                last_pct = pct

            file_path = row["file_path"]
            ext = (row["extension"] or "").lower()
            width = 0
            height = 0
            try:
                width = int(row["width"] or 0)
                height = int(row["height"] or 0)
            except (ValueError, TypeError):
                pass

            # Gather data for multi-dimensional scoring
            from constants import get_format_family
            fmt_family = get_format_family(ext)
            file_size = int(row["size_bytes"] or 0) if "size_bytes" in row.keys() else 0
            has_exif_date = bool(row["exif_datetime"]) if "exif_datetime" in row.keys() else False
            has_gps = bool(row["gps_latitude"]) if "gps_latitude" in row.keys() else False
            has_camera = bool(row["camera_make"]) if "camera_make" in row.keys() else False

            result = _assess_one(file_path, ext, width, height,
                                 fmt_family, file_size,
                                 has_exif_date, has_gps, has_camera)
            if result is None:
                if ext in IMAGE_EXTS:
                    errors += 1
                continue

            conn.execute(
                "UPDATE photos SET blur_score = ?, brightness = ?, contrast = ?, "
                "quality_score = ?, sharpness_score = ?, exposure_score = ?, "
                "contrast_score = ?, resolution_score = ?, format_score = ?, "
                "filesize_score = ?, exif_score = ? "
                "WHERE file_path = ?",
                (result["blur_score"], result["brightness"],
                 result["contrast"], result["quality_score"],
                 result["sharpness_score"], result["exposure_score"],
                 result["contrast_score"], result["resolution_score"],
                 result["format_score"], result["filesize_score"],
                 result["exif_score"], file_path),
            )
            conn.commit()
            assessed += 1

            if report_path:
                report_rows.append({
                    "file_path": file_path,
                    "filename": row["filename"] or "",
                    "extension": ext,
                    "width": width,
                    "height": height,
                    "category": row["category"] or "",
                    "blur_score": round(result["blur_score"], 2) if result["blur_score"] >= 0 else "",
                    "brightness": round(result["brightness"], 2) if result["brightness"] >= 0 else "",
                    "contrast": round(result["contrast"], 2) if result["contrast"] >= 0 else "",
                    "quality_score": result["quality_score"],
                    "sharpness": result["sharpness_score"],
                    "exposure": result["exposure_score"],
                    "contrast_dim": result["contrast_score"],
                    "resolution": result["resolution_score"],
                    "format": result["format_score"],
                    "filesize": result["filesize_score"],
                    "exif": result["exif_score"],
                })
    else:
        # Parallel mode — compute in threads, batch-write to DB
        from constants import get_format_family
        tasks = []
        for row in rows:
            ext = (row["extension"] or "").lower()
            if ext not in IMAGE_EXTS:
                continue
            file_path = row["file_path"]
            width = 0
            height = 0
            try:
                width = int(row["width"] or 0)
                height = int(row["height"] or 0)
            except (ValueError, TypeError):
                pass

            fmt_family = get_format_family(ext)
            file_size = int(row["size_bytes"] or 0) if "size_bytes" in row.keys() else 0
            has_exif_date = bool(row["exif_datetime"]) if "exif_datetime" in row.keys() else False
            has_gps = bool(row["gps_latitude"]) if "gps_latitude" in row.keys() else False
            has_camera = bool(row["camera_make"]) if "camera_make" in row.keys() else False

            tasks.append((file_path, ext, width, height, fmt_family, file_size,
                          has_exif_date, has_gps, has_camera, row))

        done_count = 0
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            future_to_data = {
                executor.submit(_assess_one, fp, ext, w, h, ff, fs, ed, gps, cam): (fp, ext, w, h, ff, fs, ed, gps, cam, row)
                for fp, ext, w, h, ff, fs, ed, gps, cam, row in tasks
            }
            for future in as_completed(future_to_data):
                done_count += 1
                pct = done_count * 100 // len(tasks)
                if pct >= last_pct + 5 or done_count == 1:
                    print(f"  Assessing... {done_count}/{len(tasks)} ({pct}%)")
                    last_pct = pct

                fp, ext, w, h, ff, fs, ed, gps, cam, row = future_to_data[future]
                result = future.result()
                if result is None:
                    errors += 1
                    continue

                conn.execute(
                    "UPDATE photos SET blur_score = ?, brightness = ?, contrast = ?, "
                    "quality_score = ?, sharpness_score = ?, exposure_score = ?, "
                    "contrast_score = ?, resolution_score = ?, format_score = ?, "
                    "filesize_score = ?, exif_score = ? "
                    "WHERE file_path = ?",
                    (result["blur_score"], result["brightness"],
                     result["contrast"], result["quality_score"],
                     result["sharpness_score"], result["exposure_score"],
                     result["contrast_score"], result["resolution_score"],
                     result["format_score"], result["filesize_score"],
                     result["exif_score"], fp),
                )
                assessed += 1

                if report_path:
                    report_rows.append({
                        "file_path": fp,
                        "filename": row["filename"] or "",
                        "extension": ext,
                        "width": w,
                        "height": h,
                        "category": row["category"] or "",
                        "blur_score": round(result["blur_score"], 2) if result["blur_score"] >= 0 else "",
                        "brightness": round(result["brightness"], 2) if result["brightness"] >= 0 else "",
                        "contrast": round(result["contrast"], 2) if result["contrast"] >= 0 else "",
                        "quality_score": result["quality_score"],
                        "sharpness": result["sharpness_score"],
                        "exposure": result["exposure_score"],
                        "contrast_dim": result["contrast_score"],
                        "resolution": result["resolution_score"],
                        "format": result["format_score"],
                        "filesize": result["filesize_score"],
                        "exif": result["exif_score"],
                    })

        # Batch commit all results
        conn.commit()

    conn.close()

    # Write report
    if report_path and report_rows:
        _write_report(report_rows, report_path)

    # Summary stats
    summary = {
        "total": total,
        "assessed": assessed,
        "errors": errors,
    }

    return summary


def _write_report(rows: list, path: str) -> None:
    """Write quality report to CSV or JSON."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "csv"

    if ext == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
    else:
        fieldnames = [
            "file_path", "filename", "extension", "width", "height",
            "category", "blur_score", "brightness", "contrast", "quality_score",
            "sharpness", "exposure", "contrast_dim", "resolution",
            "format", "filesize", "exif",
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
        description="Assess photo quality — blur, brightness, contrast, and overall score")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index (from scan_photos.py)")
    parser.add_argument("--report", "-r", dest="report", default="",
                        help="Also export a quality report (.csv or .json)")
    parser.add_argument("--incremental", action="store_true",
                        help="Only assess images without existing quality scores")
    parser.add_argument("--parallel", "-p", type=int, default=1,
                        help="Number of parallel workers (default: 1, try 4 for speed)")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    if not PILLOW_AVAILABLE:
        print("Error: Pillow is required for quality assessment.", file=sys.stderr)
        print("       Install with: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    summary = assess_quality(
        os.path.abspath(args.index),
        incremental=args.incremental,
        report_path=os.path.abspath(args.report) if args.report else None,
        parallel=args.parallel,
    )

    print(f"\n{'=' * 50}")
    print(f"Quality Assessment Complete")
    print(f"  Images scanned:   {summary['total']}")
    print(f"  Assessed:         {summary['assessed']}")
    if summary['errors'] > 0:
        print(f"  Errors (skipped): {summary['errors']}")
    print(f"\n  Quality scores written to: {args.index}")
    print(f"  Columns added: blur_score, brightness, contrast, quality_score")
    print(f"  Dimension scores: sharpness, exposure, contrast, resolution, format, filesize, exif")


if __name__ == "__main__":
    main()
