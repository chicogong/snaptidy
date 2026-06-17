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
                          width: int = 0, height: int = 0) -> int:
    """Compute composite quality score (0-100).

    Components:
      40% — Sharpness (blur score mapped to 0-40)
      25% — Exposure quality (brightness mapped to 0-25, penalize too dark/bright)
      20% — Contrast (contrast mapped to 0-20)
      15% — Resolution (pixel count mapped to 0-15)

    Returns integer 0-100.
    """
    score = 0.0

    # Sharpness component (0-40)
    # Map blur: <30 → 5, 30-80 → 15, 80-200 → 30, >200 → 40
    if blur >= 0:
        if blur < 30:
            sharp = 5 + (blur / 30) * 10
        elif blur < 80:
            sharp = 15 + ((blur - 30) / 50) * 15
        elif blur < 200:
            sharp = 30 + ((blur - 80) / 120) * 8
        else:
            sharp = 38 + min((blur - 200) / 500, 1) * 2
        score += min(sharp, 40)
    else:
        score += 20  # Unknown, give average

    # Exposure component (0-25)
    # Optimal brightness: 80-140 (well-exposed)
    # Penalize: <60 (too dark), >200 (too bright/clipped)
    if brightness >= 0:
        if 80 <= brightness <= 140:
            exposure = 25
        elif 60 <= brightness < 80:
            exposure = 15 + ((brightness - 60) / 20) * 10
        elif 140 < brightness <= 180:
            exposure = 25 - ((brightness - 140) / 40) * 10
        elif brightness < 60:
            exposure = max(0, (brightness / 60) * 15)
        else:  # > 180
            exposure = max(0, 15 - ((brightness - 180) / 75) * 15)
        score += min(exposure, 25)
    else:
        score += 12  # Unknown

    # Contrast component (0-20)
    # Optimal: 40-80 (good contrast), <25 (flat), >90 (harsh)
    if contrast >= 0:
        if 40 <= contrast <= 80:
            cont = 20
        elif 25 <= contrast < 40:
            cont = 12 + ((contrast - 25) / 15) * 8
        elif 80 < contrast <= 100:
            cont = 20 - ((contrast - 80) / 20) * 5
        elif contrast < 25:
            cont = max(0, (contrast / 25) * 12)
        else:  # > 100
            cont = max(0, 15 - ((contrast - 100) / 28) * 15)
        score += min(cont, 20)
    else:
        score += 10  # Unknown

    # Resolution component (0-15)
    # Map pixel count: <1MP → 3, 1-8MP → 6, 8-20MP → 10, >20MP → 15
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
        score += 7  # Unknown

    return max(0, min(100, int(round(score))))


# ---------------------------------------------------------------------------
# DB schema migration
# ---------------------------------------------------------------------------

QUALITY_COLUMNS = [
    ("blur_score", "REAL DEFAULT -1"),
    ("brightness", "REAL DEFAULT -1"),
    ("contrast", "REAL DEFAULT -1"),
    ("quality_score", "INTEGER DEFAULT -1"),
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

def _assess_one(file_path: str, ext: str, width: int, height: int) -> dict | None:
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
            quality = compute_quality_score(blur, brightness, contrast, width, height)

        return {
            "file_path": file_path,
            "blur_score": blur,
            "brightness": brightness,
            "contrast": contrast,
            "quality_score": quality,
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

    # Build query
    query = """
        SELECT file_path, filename, extension, width, height, category
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

            result = _assess_one(file_path, ext, width, height)
            if result is None:
                if ext in IMAGE_EXTS:
                    errors += 1
                continue

            conn.execute(
                "UPDATE photos SET blur_score = ?, brightness = ?, contrast = ?, quality_score = ? "
                "WHERE file_path = ?",
                (result["blur_score"], result["brightness"],
                 result["contrast"], result["quality_score"], file_path),
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
                })
    else:
        # Parallel mode — compute in threads, batch-write to DB
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
            tasks.append((file_path, ext, width, height, row))

        done_count = 0
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            future_to_row = {
                executor.submit(_assess_one, fp, ext, w, h): (fp, ext, w, h, row)
                for fp, ext, w, h, row in tasks
            }
            for future in as_completed(future_to_row):
                done_count += 1
                pct = done_count * 100 // len(tasks)
                if pct >= last_pct + 5 or done_count == 1:
                    print(f"  Assessing... {done_count}/{len(tasks)} ({pct}%)")
                    last_pct = pct

                fp, ext, w, h, row = future_to_row[future]
                result = future.result()
                if result is None:
                    errors += 1
                    continue

                conn.execute(
                    "UPDATE photos SET blur_score = ?, brightness = ?, contrast = ?, quality_score = ? "
                    "WHERE file_path = ?",
                    (result["blur_score"], result["brightness"],
                     result["contrast"], result["quality_score"], fp),
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


if __name__ == "__main__":
    main()
