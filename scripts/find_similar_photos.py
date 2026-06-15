#!/usr/bin/env python3
"""Find perceptually similar images — pHash, scaled duplicates, cross-format duplicates.

Reads the metadata index (SQLite DB) and groups similar images using three modes:

1. **pHash** (default) — Groups by identical or fuzzy perceptual hash.
2. **Scaled** (--detect-scaled) — Detects the same photo at different resolutions
   (e.g., original 4000x3000 vs WeChat compressed 800x600). Uses aspect-ratio
   matching + dimension-ratio verification + pHash similarity.
3. **Cross-format** (--detect-cross-format) — Detects the same photo saved in
   different formats (e.g., iPhone HEIC original + JPEG export). Uses same
   dimensions + same aspect ratio + pHash similarity.
"""

import argparse
import csv
import math
import os
import sqlite3
import sys
from collections import defaultdict

try:
    import imagehash
except ImportError:
    print("imagehash is required. Install with: pip install imagehash", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Mode 1: pHash matching (original behavior)
# ---------------------------------------------------------------------------

def group_by_phash_db(index_path: str, threshold: int = 0) -> list:
    """Group by pHash from SQLite database."""
    conn = sqlite3.connect(index_path)

    if threshold == 0:
        # Exact pHash match (fast)
        cursor = conn.execute("""
            SELECT phash, file_path FROM photos
            WHERE phash != '' AND phash IS NOT NULL
            AND phash IN (
                SELECT phash FROM photos
                WHERE phash != '' AND phash IS NOT NULL
                GROUP BY phash
                HAVING COUNT(*) > 1
            )
            ORDER BY phash, file_path
        """)
        groups = {}
        for ph, path in cursor:
            groups.setdefault(ph, []).append(path)
        conn.close()

        result = []
        group_id = 0
        for ph, paths in groups.items():
            group_id += 1
            for p in paths:
                result.append({"group_id": group_id, "phash": ph,
                               "file_path": p, "match_type": "exact_phash"})
        return result
    else:
        # Fuzzy match using Hamming distance (slower, pairwise comparison)
        cursor = conn.execute("""
            SELECT phash, file_path FROM photos
            WHERE phash != '' AND phash IS NOT NULL
            ORDER BY phash
        """)
        all_entries = [(row[0], row[1]) for row in cursor]
        conn.close()

        # Group by fuzzy pHash matching
        visited = set()
        groups = {}
        group_id = 0
        for i, (ph1, path1) in enumerate(all_entries):
            if path1 in visited:
                continue
            hash1 = imagehash.hex_to_hash(ph1)
            group_members = [path1]
            for j in range(i + 1, len(all_entries)):
                ph2, path2 = all_entries[j]
                if path2 in visited:
                    continue
                hash2 = imagehash.hex_to_hash(ph2)
                if hash1 - hash2 <= threshold:
                    group_members.append(path2)
                    visited.add(path2)

            if len(group_members) > 1:
                group_id += 1
                groups[group_id] = (ph1, group_members)
                visited.add(path1)

        result = []
        for gid, (ph, paths) in groups.items():
            for p in paths:
                result.append({"group_id": gid, "phash": ph,
                               "file_path": p, "match_type": "fuzzy_phash"})
        return result


def group_by_phash_csv(index_path: str) -> list:
    """Group by pHash from CSV file (fallback)."""
    groups = {}
    with open(index_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ph = row.get("phash", "")
            if ph:
                groups.setdefault(ph, []).append(row.get("file_path"))

    result = []
    group_id = 0
    for ph, paths in groups.items():
        if len(paths) > 1:
            group_id += 1
            for p in paths:
                result.append({"group_id": group_id, "phash": ph,
                               "file_path": p, "match_type": "exact_phash"})
    return result


# ---------------------------------------------------------------------------
# Mode 2: Scaled duplicate detection
# ---------------------------------------------------------------------------

# Aspect ratio tolerance — 1.5% difference is acceptable
ASPECT_RATIO_TOLERANCE = 0.015

# Minimum dimension ratio to consider as "scaled" (smaller must be ≥30% of larger)
MIN_SCALE_RATIO = 0.3

# Hamming distance threshold for scaled duplicate verification
SCALED_PHASH_THRESHOLD = 10


def _aspect_ratios_similar(ar1: float, ar2: float, tolerance: float = ASPECT_RATIO_TOLERANCE) -> bool:
    """Check if two aspect ratios are within tolerance."""
    if ar1 <= 0 or ar2 <= 0:
        return False
    return abs(ar1 - ar2) / max(ar1, ar2) <= tolerance


def _is_scaled_pair(w1: int, h1: int, w2: int, h2: int) -> bool:
    """Check if two images have a clear scaling relationship.

    Returns True if one image's dimensions are approximately an integer
    or half-integer multiple of the other's (e.g., 2x, 3x, 0.5x, 1.5x).
    """
    if w1 <= 0 or h1 <= 0 or w2 <= 0 or h2 <= 0:
        return False

    # Check width ratio
    rw = w1 / w2
    rh = h1 / h2

    # Both ratios should be close to the same value (consistent scaling)
    if abs(rw - rh) / max(rw, rh) > 0.1:  # 10% tolerance for ratio consistency
        return False

    # The common ratio should be ≥ MIN_SCALE_RATIO
    ratio = min(rw, rh)  # The smaller ratio (how much the smaller image is of the larger)
    if ratio < MIN_SCALE_RATIO:
        return False

    # Check if the ratio is close to a simple fraction (1/1, 1/2, 1/3, 2/3, etc.)
    # This helps filter false positives from unrelated images with similar aspect ratios
    # ratio = min(rw, rh), so for 2x scaling, ratio=2.0 (larger/smaller)
    for denom in range(1, 7):
        for numer in range(1, denom + 1):
            target = denom / numer
            if abs(ratio - target) / target < 0.12:  # 12% tolerance
                return True

    return False


def detect_scaled_duplicates_db(index_path: str, phash_threshold: int = SCALED_PHASH_THRESHOLD) -> list:
    """Detect scaled duplicates: same photo at different resolutions.

    Algorithm:
    1. Group images by aspect ratio (within tolerance)
    2. Within each group, check dimension ratio for scaling relationship
    3. Verify with pHash similarity
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Load all images with dimensions and phash
    cursor = conn.execute("""
        SELECT file_path, width, height, phash, aspect_ratio, extension, size_bytes
        FROM photos
        WHERE phash != '' AND phash IS NOT NULL
        AND width != '' AND height != '' AND width != '0' AND height != '0'
        AND media_type = 'image'
    """)
    entries = []
    for row in cursor:
        try:
            w = int(row["width"])
            h = int(row["height"])
        except (ValueError, TypeError):
            continue
        ar_str = row["aspect_ratio"]
        try:
            ar = float(ar_str) if ar_str else w / h
        except (ValueError, TypeError):
            ar = w / h
        entries.append({
            "path": row["file_path"],
            "width": w,
            "height": h,
            "aspect_ratio": ar,
            "phash": row["phash"],
            "extension": row["extension"],
            "size_bytes": row["size_bytes"],
        })
    conn.close()

    # Group by rounded aspect ratio (bucket size: 0.01)
    ar_buckets = defaultdict(list)
    for entry in entries:
        bucket = round(entry["aspect_ratio"], 2)
        ar_buckets[bucket].append(entry)

    # Also check adjacent buckets (ar 1.33 could match 1.34)
    # We merge buckets that are close
    merged_groups = _merge_nearby_buckets(ar_buckets)

    # Within each merged group, find scaled pairs
    visited = set()
    groups = {}
    group_id = 0

    for bucket_entries in merged_groups:
        if len(bucket_entries) < 2:
            continue

        for i in range(len(bucket_entries)):
            e1 = bucket_entries[i]
            if e1["path"] in visited:
                continue
            hash1 = imagehash.hex_to_hash(e1["phash"])
            group_members = [e1]

            for j in range(i + 1, len(bucket_entries)):
                e2 = bucket_entries[j]
                if e2["path"] in visited:
                    continue

                # Check aspect ratio similarity
                if not _aspect_ratios_similar(e1["aspect_ratio"], e2["aspect_ratio"]):
                    continue

                # Check dimension scaling relationship
                if not _is_scaled_pair(e1["width"], e1["height"], e2["width"], e2["height"]):
                    continue

                # Verify with pHash
                hash2 = imagehash.hex_to_hash(e2["phash"])
                if hash1 - hash2 <= phash_threshold:
                    group_members.append(e2)
                    visited.add(e2["path"])

            if len(group_members) > 1:
                group_id += 1
                groups[group_id] = group_members
                visited.add(e1["path"])

    result = []
    for gid, members in groups.items():
        for m in members:
            result.append({
                "group_id": gid,
                "phash": m["phash"],
                "file_path": m["path"],
                "match_type": "scaled",
            })
    return result


def _merge_nearby_buckets(ar_buckets: dict) -> list:
    """Merge aspect ratio buckets that are within tolerance of each other."""
    if not ar_buckets:
        return []

    sorted_buckets = sorted(ar_buckets.keys())
    merged = []
    current_group = list(ar_buckets[sorted_buckets[0]])

    for i in range(1, len(sorted_buckets)):
        prev_ar = sorted_buckets[i - 1]
        curr_ar = sorted_buckets[i]

        if abs(prev_ar - curr_ar) / max(prev_ar, curr_ar) <= ASPECT_RATIO_TOLERANCE * 2:
            # Merge: close enough
            current_group.extend(ar_buckets[curr_ar])
        else:
            merged.append(current_group)
            current_group = list(ar_buckets[curr_ar])

    merged.append(current_group)
    return merged


# ---------------------------------------------------------------------------
# Mode 3: Cross-format duplicate detection
# ---------------------------------------------------------------------------

# Hamming distance threshold for cross-format verification
# Higher than pHash default because format conversion changes pixel values
CROSS_FORMAT_PHASH_THRESHOLD = 12


def detect_cross_format_duplicates_db(index_path: str, phash_threshold: int = CROSS_FORMAT_PHASH_THRESHOLD) -> list:
    """Detect cross-format duplicates: same photo in different formats.

    Typical scenario: iPhone shoots HEIC, exports JPEG — both exist on disk.

    Algorithm:
    1. Group images by aspect ratio
    2. Within same aspect ratio, find pairs where format_family differs
    3. Check if dimensions are very close (within 2 pixels — format conversion may crop 1px)
    4. Verify with pHash similarity
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Load all images with dimensions and phash
    cursor = conn.execute("""
        SELECT file_path, width, height, phash, aspect_ratio, format_family,
               extension, size_bytes
        FROM photos
        WHERE phash != '' AND phash IS NOT NULL
        AND width != '' AND height != '' AND width != '0' AND height != '0'
        AND media_type = 'image'
        AND format_family != ''
    """)
    entries = []
    for row in cursor:
        try:
            w = int(row["width"])
            h = int(row["height"])
        except (ValueError, TypeError):
            continue
        ar_str = row["aspect_ratio"]
        try:
            ar = float(ar_str) if ar_str else w / h
        except (ValueError, TypeError):
            ar = w / h
        entries.append({
            "path": row["file_path"],
            "width": w,
            "height": h,
            "aspect_ratio": ar,
            "phash": row["phash"],
            "format_family": row["format_family"],
            "extension": row["extension"],
            "size_bytes": row["size_bytes"],
        })
    conn.close()

    # Group by aspect ratio bucket
    ar_buckets = defaultdict(list)
    for entry in entries:
        bucket = round(entry["aspect_ratio"], 2)
        ar_buckets[bucket].append(entry)

    merged_groups = _merge_nearby_buckets(ar_buckets)

    # Within each group, find cross-format pairs
    visited = set()
    groups = {}
    group_id = 0

    for bucket_entries in merged_groups:
        if len(bucket_entries) < 2:
            continue

        # Sub-group by format_family first
        by_format = defaultdict(list)
        for e in bucket_entries:
            by_format[e["format_family"]].append(e)

        # Need at least 2 different format families
        format_families = list(by_format.keys())
        if len(format_families) < 2:
            continue

        # Compare across format families
        for fi in range(len(format_families)):
            for fj in range(fi + 1, len(format_families)):
                fam_i = format_families[fi]
                fam_j = format_families[fj]

                for e1 in by_format[fam_i]:
                    if e1["path"] in visited:
                        continue
                    hash1 = imagehash.hex_to_hash(e1["phash"])
                    group_members = [e1]

                    for e2 in by_format[fam_j]:
                        if e2["path"] in visited:
                            continue

                        # Check aspect ratio similarity
                        if not _aspect_ratios_similar(e1["aspect_ratio"], e2["aspect_ratio"]):
                            continue

                        # Check dimensions: must be very close (within 2px per dimension)
                        # Format conversion may add/remove 1 pixel due to chroma subsampling
                        dim_tolerance = max(2, round(max(e1["width"], e2["width"]) * 0.005))
                        if (abs(e1["width"] - e2["width"]) > dim_tolerance or
                                abs(e1["height"] - e2["height"]) > dim_tolerance):
                            continue

                        # Verify with pHash (higher threshold for cross-format)
                        hash2 = imagehash.hex_to_hash(e2["phash"])
                        if hash1 - hash2 <= phash_threshold:
                            group_members.append(e2)
                            visited.add(e2["path"])

                    if len(group_members) > 1:
                        group_id += 1
                        groups[group_id] = group_members
                        visited.add(e1["path"])

    result = []
    for gid, members in groups.items():
        for m in members:
            result.append({
                "group_id": gid,
                "phash": m["phash"],
                "file_path": m["path"],
                "match_type": "cross_format",
            })
    return result


# ---------------------------------------------------------------------------
# Mode 4: Burst detection via SubSecTime
# ---------------------------------------------------------------------------

def detect_bursts_db(index_path: str) -> list:
    """Detect burst photos using SubSecTime EXIF data.

    Groups photos taken within the same second (same exif_datetime)
    that have different SubSecTime values, indicating burst mode.
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Find photos with subsec_time data
    cursor = conn.execute("""
        SELECT file_path, exif_datetime, subsec_time, phash, extension
        FROM photos
        WHERE exif_datetime != '' AND exif_datetime IS NOT NULL
        AND subsec_time != '' AND subsec_time IS NOT NULL
        AND media_type = 'image'
        ORDER BY exif_datetime, subsec_time
    """)
    entries = []
    for row in cursor:
        entries.append({
            "path": row["file_path"],
            "exif_datetime": row["exif_datetime"],
            "subsec_time": row["subsec_time"],
            "phash": row["phash"],
            "extension": row["extension"],
        })
    conn.close()

    # Group by exif_datetime (same second)
    by_second = defaultdict(list)
    for e in entries:
        by_second[e["exif_datetime"]].append(e)

    # Find groups with multiple photos in the same second
    visited = set()
    groups = {}
    group_id = 0

    for dt, second_entries in by_second.items():
        if len(second_entries) < 2:
            continue

        # Check if these have distinct subsec times (burst) vs same (duplicate)
        subsec_values = set(e["subsec_time"] for e in second_entries)
        if len(subsec_values) < 2:
            # Same subsec time — likely exact duplicate, not burst
            continue

        group_id += 1
        for e in second_entries:
            if e["path"] not in visited:
                groups.setdefault(group_id, []).append(e)
                visited.add(e["path"])

    result = []
    for gid, members in groups.items():
        for m in members:
            result.append({
                "group_id": gid,
                "phash": m["phash"],
                "file_path": m["path"],
                "match_type": "burst_subsec",
            })
    return result


# ---------------------------------------------------------------------------
# Combined mode: run all detection methods
# ---------------------------------------------------------------------------

def detect_all_db(index_path: str, phash_threshold: int = 0) -> list:
    """Run all duplicate detection methods and merge results."""
    all_results = []

    # pHash matching
    phash_results = group_by_phash_db(index_path, threshold=phash_threshold)
    all_results.extend(phash_results)

    # Scaled duplicates
    scaled_results = detect_scaled_duplicates_db(index_path)
    all_results.extend(scaled_results)

    # Cross-format duplicates
    cross_results = detect_cross_format_duplicates_db(index_path)
    all_results.extend(cross_results)

    # Burst detection
    burst_results = detect_bursts_db(index_path)
    all_results.extend(burst_results)

    # Re-number group IDs to be unique across all methods
    if not all_results:
        return []

    # Group by group_id within each method, then re-number
    method_groups = defaultdict(list)
    for r in all_results:
        key = (r["match_type"], r["group_id"])
        method_groups[key].append(r)

    result = []
    new_gid = 0
    for key in sorted(method_groups.keys(), key=lambda k: k[0]):
        new_gid += 1
        for r in method_groups[key]:
            r["group_id"] = new_gid
            result.append(r)

    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_csv(entries, output_path):
    fieldnames = ["group_id", "phash", "file_path", "match_type"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find similar images: pHash, scaled duplicates, cross-format duplicates")
    parser.add_argument("--index", required=True, help="Path to metadata index (.db or .csv)")
    parser.add_argument("--output", required=True, help="Path to output CSV for similar images")
    parser.add_argument("--threshold", type=int, default=0,
                        help="Hamming distance threshold for fuzzy pHash matching (0=exact, default: 0)")
    parser.add_argument("--detect-scaled", action="store_true",
                        help="Detect scaled duplicates (same photo at different resolutions)")
    parser.add_argument("--detect-cross-format", action="store_true",
                        help="Detect cross-format duplicates (e.g., HEIC + JPEG of same photo)")
    parser.add_argument("--detect-bursts", action="store_true",
                        help="Detect burst photos using SubSecTime EXIF data")
    parser.add_argument("--detect-all", action="store_true",
                        help="Run all detection methods (pHash + scaled + cross-format + bursts)")
    parser.add_argument("--scaled-threshold", type=int, default=SCALED_PHASH_THRESHOLD,
                        help=f"Hamming distance threshold for scaled duplicate verification (default: {SCALED_PHASH_THRESHOLD})")
    parser.add_argument("--cross-format-threshold", type=int, default=CROSS_FORMAT_PHASH_THRESHOLD,
                        help=f"Hamming distance threshold for cross-format verification (default: {CROSS_FORMAT_PHASH_THRESHOLD})")
    args = parser.parse_args()
    index_path = os.path.abspath(args.index)
    output_path = os.path.abspath(args.output)

    if not index_path.endswith(".db"):
        # CSV fallback — only pHash mode supported
        entries = group_by_phash_csv(index_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        write_csv(entries, output_path)
        num_groups = len(set(e["group_id"] for e in entries)) if entries else 0
        print(f"Found {len(entries)} images in {num_groups} perceptual groups (CSV mode, pHash only).")
        return

    # Determine which detection methods to run
    run_all = args.detect_all
    run_phash = not (args.detect_scaled or args.detect_cross_format or args.detect_bursts) or run_all
    run_scaled = args.detect_scaled or run_all
    run_cross = args.detect_cross_format or run_all
    run_bursts = args.detect_bursts or run_all

    all_results = []
    method_stats = {}

    if run_phash:
        phash_results = group_by_phash_db(index_path, threshold=args.threshold)
        all_results.extend(phash_results)
        n = len(set(e["group_id"] for e in phash_results)) if phash_results else 0
        method_stats["pHash"] = (len(phash_results), n)

    if run_scaled:
        scaled_results = detect_scaled_duplicates_db(index_path, phash_threshold=args.scaled_threshold)
        all_results.extend(scaled_results)
        n = len(set(e["group_id"] for e in scaled_results)) if scaled_results else 0
        method_stats["Scaled"] = (len(scaled_results), n)

    if run_cross:
        cross_results = detect_cross_format_duplicates_db(index_path, phash_threshold=args.cross_format_threshold)
        all_results.extend(cross_results)
        n = len(set(e["group_id"] for e in cross_results)) if cross_results else 0
        method_stats["Cross-format"] = (len(cross_results), n)

    if run_bursts:
        burst_results = detect_bursts_db(index_path)
        all_results.extend(burst_results)
        n = len(set(e["group_id"] for e in burst_results)) if burst_results else 0
        method_stats["Burst"] = (len(burst_results), n)

    # Re-number group IDs
    if all_results:
        method_groups = defaultdict(list)
        for r in all_results:
            key = (r["match_type"], r["group_id"])
            method_groups[key].append(r)

        new_gid = 0
        for key in sorted(method_groups.keys(), key=lambda k: (k[0], k[1])):
            new_gid += 1
            for r in method_groups[key]:
                r["group_id"] = new_gid

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_csv(all_results, output_path)

    total_groups = len(set(e["group_id"] for e in all_results)) if all_results else 0
    print(f"Found {len(all_results)} images in {total_groups} groups.")

    for method, (count, groups) in method_stats.items():
        if count > 0:
            print(f"  {method}: {count} images in {groups} groups")


if __name__ == "__main__":
    main()
