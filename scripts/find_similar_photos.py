#!/usr/bin/env python3
"""Find perceptually similar images — pHash, scaled duplicates, cross-format duplicates, Apple quality vector.

Reads the metadata index (SQLite DB) and groups similar images using modes:

1. **pHash** (default) — Groups by identical or fuzzy perceptual hash.
2. **Scaled** (--detect-scaled) — Detects the same photo at different resolutions
   (e.g., original 4000x3000 vs WeChat compressed 800x600). Uses aspect-ratio
   matching + dimension-ratio verification + pHash similarity.
3. **Cross-format** (--detect-cross-format) — Detects the same photo saved in
   different formats (e.g., iPhone HEIC original + JPEG export). Uses same
   dimensions + same aspect ratio + pHash similarity.
4. **Apple quality vector** (--detect-apple-ql) — Uses Apple's pre-computed 17-dim
   ML feature vectors from ZCOMPUTEDASSETATTRIBUTES for zero-dependency cosine
   similarity detection. Only available for Photos.app library scans.
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
    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False


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

        # Sort by pixel count (area) for efficient range scanning
        bucket_entries.sort(key=lambda e: e["width"] * e["height"])

        for i in range(len(bucket_entries)):
            e1 = bucket_entries[i]
            if e1["path"] in visited:
                continue
            hash1 = imagehash.hex_to_hash(e1["phash"])
            group_members = [e1]
            area1 = e1["width"] * e1["height"]

            for j in range(i + 1, len(bucket_entries)):
                e2 = bucket_entries[j]
                if e2["path"] in visited:
                    continue

                area2 = e2["width"] * e2["height"]
                # Early exit: if the larger image is >4x the smaller, skip
                # (scaled detection only checks 1x,2x,3x,4x ratios)
                if area2 > area1 * 16:
                    break

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
        # Optimization: index by (w, h) for O(1) dimension lookup
        for fi in range(len(format_families)):
            for fj in range(fi + 1, len(format_families)):
                fam_i = format_families[fi]
                fam_j = format_families[fj]

                # Build dimension index for fam_j: (w, h) → [entries]
                dim_index_j = defaultdict(list)
                for e2 in by_format[fam_j]:
                    dim_index_j[(e2["width"], e2["height"])].append(e2)

                for e1 in by_format[fam_i]:
                    if e1["path"] in visited:
                        continue
                    hash1 = imagehash.hex_to_hash(e1["phash"])
                    group_members = [e1]

                    # Only check entries in fam_j with matching dimensions
                    dim_tolerance = max(2, round(e1["width"] * 0.005))
                    for dw in range(-dim_tolerance, dim_tolerance + 1):
                        for dh in range(-dim_tolerance, dim_tolerance + 1):
                            key = (e1["width"] + dw, e1["height"] + dh)
                            for e2 in dim_index_j.get(key, []):
                                if e2["path"] in visited:
                                    continue

                                # Check aspect ratio similarity
                                if not _aspect_ratios_similar(e1["aspect_ratio"], e2["aspect_ratio"]):
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

def detect_apple_quality_similar_db(index_path: str, threshold: float = 0.92) -> list:
    """Detect similar photos using Apple's pre-computed 17-dim ML quality vectors.

    Uses cosine similarity between quality vectors from ZCOMPUTEDASSETATTRIBUTES.
    This is a zero-dependency detection method (no Pillow/imagehash needed).
    Only works for Photos.app library scans where quality vectors are available.

    Args:
        index_path: Path to SQLite metadata index
        threshold: Cosine similarity threshold (0.0-1.0, default 0.92)
    """
    import json as _json

    conn = sqlite3.connect(index_path)
    cursor = conn.execute("""
        SELECT file_path, photos_quality_vector
        FROM photos
        WHERE photos_quality_vector != '' AND photos_quality_vector IS NOT NULL
    """)

    entries_with_vector = []
    for path, vector_json in cursor:
        try:
            vector = _json.loads(vector_json)
            if len(vector) == 17 and any(v != 0.0 for v in vector):
                entries_with_vector.append((path, vector))
        except (ValueError, TypeError):
            continue
    conn.close()

    if len(entries_with_vector) < 2:
        return []

    # Union-Find for proper group merging
    # Each path starts as its own group; similar pairs get merged
    parent = {}  # path -> root path

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])  # path compression
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Build similarity pairs using union-find
    for i in range(len(entries_with_vector)):
        path1, vec1 = entries_with_vector[i]
        parent.setdefault(path1, path1)

        mag1 = math.sqrt(sum(v * v for v in vec1))
        if mag1 == 0:
            continue

        for j in range(i + 1, len(entries_with_vector)):
            path2, vec2 = entries_with_vector[j]
            parent.setdefault(path2, path2)

            dot = sum(a * b for a, b in zip(vec1, vec2))
            mag2 = math.sqrt(sum(v * v for v in vec2))
            if mag2 == 0:
                continue

            similarity = dot / (mag1 * mag2)
            if similarity >= threshold:
                union(path1, path2)

    # Collect groups from union-find roots
    root_groups = defaultdict(set)
    for path in parent:
        root_groups[find(path)].add(path)

    # Only keep groups with 2+ members
    result = []
    group_id = 0
    for root, members in sorted(root_groups.items()):
        if len(members) < 2:
            continue
        group_id += 1
        for path in sorted(members):
            result.append({
                "group_id": group_id,
                "phash": "",
                "file_path": path,
                "match_type": "apple_quality_vector",
            })

    return result


def write_csv(entries, output_path):
    fieldnames = ["group_id", "phash", "file_path", "match_type"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)


def write_human(entries, output_path, index_path: str = ""):
    """Write human-readable similar photos report."""
    # Load metadata for size info
    metadata = {}
    if index_path and index_path.endswith(".db"):
        try:
            conn = sqlite3.connect(index_path)
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT file_path, size_bytes, category FROM photos"):
                metadata[row["file_path"]] = {
                    "size": row["size_bytes"] or 0,
                    "category": row["category"] or "",
                }
            conn.close()
        except Exception:
            pass

    # Group by group_id
    groups = {}
    for e in entries:
        groups.setdefault(e["group_id"], []).append(e)

    MATCH_LABELS = {
        "exact_phash": "pHash exact match",
        "fuzzy_phash": "pHash similar",
        "scaled": "scaled duplicate",
        "cross_format": "cross-format",
        "burst_subsec": "burst",
        "apple_quality_vector": "Apple QL similar",
    }

    lines = []
    lines.append("=" * 72)
    lines.append(f"Similar Photos Report — {len(entries)} images in {len(groups)} groups")
    lines.append("=" * 72)
    lines.append("")

    # Summary by method
    method_counts = {}
    for e in entries:
        mt = e.get("match_type", "unknown")
        method_counts[mt] = method_counts.get(mt, 0) + 1

    if method_counts:
        lines.append("Detection methods:")
        for mt, count in sorted(method_counts.items()):
            label = MATCH_LABELS.get(mt, mt)
            n_groups = len(set(e["group_id"] for e in entries if e.get("match_type") == mt))
            lines.append(f"  {label}: {count} images in {n_groups} groups")
        lines.append("")

    for gid in sorted(groups.keys()):
        members = groups[gid]
        match_type = members[0].get("match_type", "")
        match_label = MATCH_LABELS.get(match_type, match_type)

        lines.append(f"Group {gid} ({match_label}, {len(members)} images)")
        for m in members:
            meta = metadata.get(m["file_path"], {})
            size_str = ""
            if meta.get("size"):
                sz = meta["size"]
                if sz >= 1_048_576:
                    size_str = f"{sz / 1_048_576:.1f}MB"
                elif sz >= 1_024:
                    size_str = f"{sz / 1_024:.1f}KB"
                else:
                    size_str = f"{sz}B"
            cat = meta.get("category", "")
            path = m["file_path"]
            if len(path) > 55:
                path = "..." + path[-52:]
            info = "  ".join(filter(None, [size_str, cat]))
            if info:
                lines.append(f"    {info:<16} {path}")
            else:
                lines.append(f"    {path}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find similar images: pHash, scaled duplicates, cross-format duplicates")
    parser.add_argument("--index", required=True, help="Path to metadata index (.db or .csv)")
    parser.add_argument("--output", required=True, help="Path to output CSV for similar images")
    parser.add_argument("--format", choices=["csv", "human"], default="csv",
                        help="Output format: csv (default) or human (readable report)")
    parser.add_argument("--threshold", type=int, default=0,
                        help="Hamming distance threshold for fuzzy pHash matching (0=exact, default: 0)")
    parser.add_argument("--detect-scaled", action="store_true",
                        help="Detect scaled duplicates (same photo at different resolutions)")
    parser.add_argument("--detect-cross-format", action="store_true",
                        help="Detect cross-format duplicates (e.g., HEIC + JPEG of same photo)")
    parser.add_argument("--detect-bursts", action="store_true",
                        help="Detect burst photos using SubSecTime EXIF data")
    parser.add_argument("--detect-apple-ql", action="store_true",
                        help="Detect similar photos using Apple's pre-computed ML quality vectors (zero-dependency)")
    parser.add_argument("--detect-all", action="store_true",
                        help="Run all detection methods (pHash + scaled + cross-format + bursts + Apple QL)")
    parser.add_argument("--apple-ql-threshold", type=float, default=0.92,
                        help="Cosine similarity threshold for Apple quality vector detection (default: 0.92)")
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
    run_phash = not (args.detect_scaled or args.detect_cross_format or args.detect_bursts or args.detect_apple_ql) or run_all
    run_scaled = args.detect_scaled or run_all
    run_cross = args.detect_cross_format or run_all
    run_bursts = args.detect_bursts or run_all
    run_apple_ql = args.detect_apple_ql or run_all

    all_results = []
    method_stats = {}

    if run_phash:
        if not IMAGEHASH_AVAILABLE:
            print("⚠️  imagehash not installed — skipping pHash detection. Install with: pip install imagehash", file=sys.stderr)
            method_stats["pHash"] = (0, 0)
        else:
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

    if run_apple_ql:
        apple_ql_results = detect_apple_quality_similar_db(
            index_path, threshold=args.apple_ql_threshold)
        all_results.extend(apple_ql_results)
        n = len(set(e["group_id"] for e in apple_ql_results)) if apple_ql_results else 0
        method_stats["Apple QL"] = (len(apple_ql_results), n)

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
    if args.format == "human":
        write_human(all_results, output_path, index_path)
    else:
        write_csv(all_results, output_path)

    total_groups = len(set(e["group_id"] for e in all_results)) if all_results else 0
    print(f"Found {len(all_results)} images in {total_groups} groups.")

    for method, (count, groups) in method_stats.items():
        if count > 0:
            print(f"  {method}: {count} images in {groups} groups")


if __name__ == "__main__":
    main()
