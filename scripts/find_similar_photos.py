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

# Optional: deep learning feature extraction (MobileNet-V3 / ResNet)
try:
    import torch
    import torchvision.transforms as transforms
    import torchvision.models as models
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Optional: ONNX Runtime (lighter alternative to PyTorch)
try:
    import onnxruntime as ort
    import numpy as np
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

# Optional: PIL for image loading in CNN mode
try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Mode 1: pHash matching (original behavior)
# ---------------------------------------------------------------------------

def group_by_phash_db(index_path: str, threshold: int = 0) -> list:
    """Group by pHash from SQLite database."""
    conn = sqlite3.connect(index_path)

    # Check if phash column exists
    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
    if "phash" not in available_cols:
        conn.close()
        if IMAGEHASH_AVAILABLE:
            print("  ⚠️  phash column not found in index — pHash detection skipped", file=sys.stderr)
            print("     Run scan_photos.py or scan_photos_library.py first to compute phash", file=sys.stderr)
        return []

    # All-zeros phash (e.g. from tiny/simple images) is meaningless — skip it
    INVALID_PHASH = "0000000000000000"

    # Build pixel-count filter for SQL if width/height columns exist
    has_dims = "width" in available_cols and "height" in available_cols
    dim_filter = ""
    if has_dims:
        dim_filter = f" AND CAST(width AS INTEGER) * CAST(height AS INTEGER) >= {PHASH_MIN_PIXELS}"

    if threshold == 0:
        # Exact pHash match (fast)
        cursor = conn.execute(f"""
            SELECT phash, file_path FROM photos
            WHERE phash != '' AND phash IS NOT NULL
            AND phash != ?
            {dim_filter}
            AND phash IN (
                SELECT phash FROM photos
                WHERE phash != '' AND phash IS NOT NULL
                AND phash != ?
                {dim_filter}
                GROUP BY phash
                HAVING COUNT(*) > 1
            )
            ORDER BY phash, file_path
        """, (INVALID_PHASH, INVALID_PHASH))
        groups = {}
        for ph, path in cursor:
            groups.setdefault(ph, []).append(path)
        conn.close()

        result = []
        group_id = 0
        for ph, paths in groups.items():
            # Skip low-entropy phash groups (tiny/simple images)
            if _is_low_entropy_phash(ph):
                continue
            group_id += 1
            for p in paths:
                result.append({"group_id": group_id, "phash": ph,
                               "file_path": p, "match_type": "exact_phash"})
        return result
    else:
        # Fuzzy match using Hamming distance (slower, pairwise comparison)
        cursor = conn.execute(f"""
            SELECT phash, file_path FROM photos
            WHERE phash != '' AND phash IS NOT NULL
            AND phash != ?
            {dim_filter}
            ORDER BY phash
        """, (INVALID_PHASH,))
        all_entries = [(row[0], row[1]) for row in cursor]
        conn.close()

        # Group by fuzzy pHash matching (skip low-entropy hashes)
        visited = set()
        groups = {}
        group_id = 0
        for i, (ph1, path1) in enumerate(all_entries):
            if path1 in visited:
                continue
            # Skip low-entropy phash
            if _is_low_entropy_phash(ph1):
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
    INVALID_PHASH = "0000000000000000"
    groups = {}
    with open(index_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ph = row.get("phash", "")
            if ph and ph != INVALID_PHASH:
                groups.setdefault(ph, []).append(row.get("file_path"))

    result = []
    group_id = 0
    for ph, paths in groups.items():
        # Skip low-entropy phash groups
        if len(paths) > 1 and not _is_low_entropy_phash(ph):
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

# pHash bit count thresholds — hashes with too few or too many set bits
# indicate low-information images (solid colors, simple patterns) where
# pHash is unreliable. 64-bit hash: skip if bits < 4 or > 60.
PHASH_MIN_BITS = 4
PHASH_MAX_BITS = 60

# Minimum pixel count for reliable phash matching.
# Images smaller than this produce unreliable perceptual hashes even if
# bit count passes the threshold. 32×32 = 1024 pixels is the practical minimum
# for pHash (which resizes to 32×32 internally — smaller inputs just get padded).
PHASH_MIN_PIXELS = 1024


def _is_low_entropy_phash(phash_hex: str, width: int = 0, height: int = 0) -> bool:
    """Return True if phash is unreliable due to low information content.

    Checks both bit count (too few/many set bits) and pixel count
    (images too small for pHash to produce meaningful hashes).
    """
    # Check pixel count if dimensions provided
    if width > 0 and height > 0 and width * height < PHASH_MIN_PIXELS:
        return True
    try:
        bits = bin(int(phash_hex, 16)).count("1")
        return bits < PHASH_MIN_BITS or bits > PHASH_MAX_BITS
    except (ValueError, TypeError):
        return True


def _aspect_ratios_similar(ar1: float, ar2: float, tolerance: float = ASPECT_RATIO_TOLERANCE) -> bool:
    """Check if two aspect ratios are within tolerance."""
    if ar1 <= 0 or ar2 <= 0:
        return False
    return abs(ar1 - ar2) / max(ar1, ar2) <= tolerance


def _is_scaled_pair(w1: int, h1: int, w2: int, h2: int) -> bool:
    """Check if two images have a clear scaling relationship.

    Returns True if one image's dimensions are approximately an integer
    or half-integer multiple of the other's (e.g., 2x, 3x, 0.5x, 1.5x).

    Note: Same-dimension images are NOT scaled duplicates — they are either
    exact duplicates (handled separately) or different photos at the same size.
    """
    if w1 <= 0 or h1 <= 0 or w2 <= 0 or h2 <= 0:
        return False

    # Same dimensions → not a scaled pair (either exact dup or different photo)
    if w1 == w2 and h1 == h2:
        return False

    # Check width ratio
    rw = w1 / w2
    rh = h1 / h2

    # Both ratios should be close to the same value (consistent scaling)
    if abs(rw - rh) / max(rw, rh) > 0.1:  # 10% tolerance for ratio consistency
        return False

    # Normalize ratio to >= 1.0 (how many times the larger image is of the smaller)
    # rw and rh are approximately equal (checked above), so use either
    ratio = max(rw, rh)
    if ratio < 1.0:
        ratio = 1.0 / ratio

    # The common ratio should be ≥ MIN_SCALE_RATIO
    if ratio < MIN_SCALE_RATIO:
        return False

    # Check if the ratio is close to a simple fraction (1/1, 1/2, 1/3, 2/3, etc.)
    # This helps filter false positives from unrelated images with similar aspect ratios
    # ratio is always >= 1.0, so for 2x scaling ratio=2.0, for 3x ratio=3.0, etc.
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
    if not IMAGEHASH_AVAILABLE:
        print("  ⚠️  imagehash not installed — scaled detection skipped", file=sys.stderr)
        return []

    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Load all images with dimensions and phash
    try:
        cursor = conn.execute("""
            SELECT file_path, width, height, phash, aspect_ratio, extension, size_bytes
            FROM photos
            WHERE phash != '' AND phash IS NOT NULL
            AND phash != '0000000000000000'
            AND width != '' AND height != '' AND width != '0' AND height != '0'
            AND media_type = 'image'
        """)
    except sqlite3.OperationalError as e:
        conn.close()
        print(f"  ⚠️  Scaled detection requires complete metadata (width, height, phash, aspect_ratio): {e}", file=sys.stderr)
        return []
    entries = []
    for row in cursor:
        try:
            w = int(row["width"])
            h = int(row["height"])
        except (ValueError, TypeError):
            continue
        # Skip low-entropy phash (includes pixel count check)
        ph = row["phash"]
        if _is_low_entropy_phash(ph, w, h):
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
            "phash": ph,
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

    # Collect scaled pairs — use pair collection + selective union
    # to avoid transitive chaining through "hub" images.
    # E.g., if ImageA (1920x1080) ↔ ScaledB (960x540) and ImageC (1920x1080) ↔ ScaledB,
    # then A and C should NOT be in the same group (they're different photos
    # that happen to have similar phash to the same hub).
    # Only union pairs with near-exact phash match (dist ≤ SCALED_UNION_THRESHOLD).
    scaled_pairs = []  # list of (path_i, path_j, hamming_distance)

    for bucket_entries in merged_groups:
        if len(bucket_entries) < 2:
            continue

        # Sort by pixel count (area) for efficient range scanning
        bucket_entries.sort(key=lambda e: e["width"] * e["height"])

        for i in range(len(bucket_entries)):
            e1 = bucket_entries[i]
            hash1 = imagehash.hex_to_hash(e1["phash"])
            area1 = e1["width"] * e1["height"]

            for j in range(i + 1, len(bucket_entries)):
                e2 = bucket_entries[j]

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
                hamming = hash1 - hash2
                if hamming <= phash_threshold:
                    # Sanity check: file sizes should roughly scale with pixel count.
                    # Skip if larger file has disproportionately MORE bytes per pixel
                    # (suggests different content, e.g. compressed screenshot vs photo).
                    size1 = e1.get("size_bytes") or 0
                    size2 = e2.get("size_bytes") or 0
                    if size1 > 0 and size2 > 0 and area1 > 0 and area2 > 0:
                        bpp1 = size1 / area1
                        bpp2 = size2 / area2
                        # Bytes-per-pixel ratio: if one is >8x the other, likely different content
                        bpp_ratio = max(bpp1, bpp2) / min(bpp1, bpp2)
                        if bpp_ratio > 8.0:
                            continue
                    scaled_pairs.append((e1["path"], e2["path"], hamming))

    # Group scaled pairs using selective union-find:
    # Only union pairs with near-exact phash match (dist ≤ SCALED_UNION_THRESHOLD).
    # This prevents transitive chaining through hub images while still correctly
    # grouping the same photo at multiple resolutions (e.g., 1x + 2x + 4x).
    SCALED_UNION_THRESHOLD = 3
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for path_i, path_j, dist in scaled_pairs:
        parent.setdefault(path_i, path_i)
        parent.setdefault(path_j, path_j)
        # Only union pairs with near-exact phash match
        if dist <= SCALED_UNION_THRESHOLD:
            union(path_i, path_j)

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
            # Look up phash from entries
            phash_val = ""
            for e in entries:
                if e["path"] == path:
                    phash_val = e["phash"]
                    break
            result.append({
                "group_id": group_id,
                "phash": phash_val,
                "file_path": path,
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
CROSS_FORMAT_PHASH_THRESHOLD = 5
# Cross-format duplicates are the SAME photo in different formats.
# phash should be nearly identical — only format conversion artifacts cause
# small differences. Threshold 5 is generous; most true matches are ≤ 2.


def detect_cross_format_duplicates_db(index_path: str, phash_threshold: int = CROSS_FORMAT_PHASH_THRESHOLD) -> list:
    """Detect cross-format duplicates: same photo in different formats.

    Typical scenario: iPhone shoots HEIC, exports JPEG — both exist on disk.

    Algorithm:
    1. Group images by aspect ratio
    2. Within same aspect ratio, find pairs where format_family differs
    3. Check if dimensions are very close (within 2 pixels — format conversion may crop 1px)
    4. Verify with pHash similarity
    """
    if not IMAGEHASH_AVAILABLE:
        print("  ⚠️  imagehash not installed — cross-format detection skipped", file=sys.stderr)
        return []

    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Load all images with dimensions and phash
    try:
        cursor = conn.execute("""
            SELECT file_path, width, height, phash, aspect_ratio, format_family,
                   extension, size_bytes
            FROM photos
            WHERE phash != '' AND phash IS NOT NULL
            AND phash != '0000000000000000'
            AND width != '' AND height != '' AND width != '0' AND height != '0'
            AND media_type = 'image'
            AND format_family != ''
        """)
    except sqlite3.OperationalError as e:
        conn.close()
        print(f"  ⚠️  Cross-format detection requires complete metadata (width, height, phash, format_family): {e}", file=sys.stderr)
        return []
    entries = []
    for row in cursor:
        try:
            w = int(row["width"])
            h = int(row["height"])
        except (ValueError, TypeError):
            continue
        # Skip low-entropy phash (includes pixel count check)
        ph = row["phash"]
        if _is_low_entropy_phash(ph, w, h):
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
            "phash": ph,
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

    # Collect cross-format pairs — do NOT use union-find here!
    # Union-find creates transitive chains that group unrelated photos:
    # PNG↔JPEG_A (dist 0) + PNG↔JPEG_B (dist 3) → A and B in same group (WRONG!)
    # Instead, collect explicit pairs. Group files that share BOTH phash match AND
    # a common source image (i.e., one photo exported to multiple formats).
    cross_pairs = []  # list of (path_i, path_j, hamming_distance)

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

                # Build dimension index for fam_j: (w, h) → [entries]
                dim_index_j = defaultdict(list)
                for e2 in by_format[fam_j]:
                    dim_index_j[(e2["width"], e2["height"])].append(e2)

                for e1 in by_format[fam_i]:
                    hash1 = imagehash.hex_to_hash(e1["phash"])

                    # Only check entries in fam_j with matching dimensions
                    dim_tolerance = max(2, round(e1["width"] * 0.005))
                    for dw in range(-dim_tolerance, dim_tolerance + 1):
                        for dh in range(-dim_tolerance, dim_tolerance + 1):
                            key = (e1["width"] + dw, e1["height"] + dh)
                            for e2 in dim_index_j.get(key, []):
                                # Check aspect ratio similarity
                                if not _aspect_ratios_similar(e1["aspect_ratio"], e2["aspect_ratio"]):
                                    continue

                                # Verify with pHash — cross-format duplicates must have
                                # nearly identical phash (same photo, different format)
                                hash2 = imagehash.hex_to_hash(e2["phash"])
                                hamming = hash1 - hash2
                                if hamming <= phash_threshold:
                                    # Size sanity check: same photo in different formats
                                    # should have comparable file sizes.
                                    size1 = e1.get("size_bytes") or 0
                                    size2 = e2.get("size_bytes") or 0
                                    if size1 > 0 and size2 > 0:
                                        ratio = max(size1, size2) / min(size1, size2)
                                        if ratio > 10.0:
                                            continue
                                    cross_pairs.append((e1["path"], e2["path"], hamming))

    # Group cross-format pairs: for each image, find all its format variants.
    # Two images are in the same group only if they are DIRECTLY paired
    # (i.e., same phash match), NOT transitively through a third image.
    # Use union-find ONLY on pairs with hamming distance 0 (exact phash match),
    # which guarantees they are the same photo.
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for path_i, path_j, dist in cross_pairs:
        parent.setdefault(path_i, path_i)
        parent.setdefault(path_j, path_j)
        # Only union pairs with exact (dist=0) or near-exact (dist≤1) phash match
        # Higher distances are likely different photos that happen to be similar
        if dist <= 1:
            union(path_i, path_j)

    # Collect groups from union-find roots
    root_groups = defaultdict(set)
    for path in parent:
        root_groups[find(path)].add(path)

    # Only keep groups with 2+ members and at least 2 format families
    result = []
    group_id = 0
    path_to_entry = {e["path"]: e for e in entries}
    for root, members in sorted(root_groups.items()):
        if len(members) < 2:
            continue
        # Verify at least 2 format families in this group
        families_in_group = set()
        for p in members:
            e = path_to_entry.get(p)
            if e:
                families_in_group.add(e["format_family"])
        if len(families_in_group) < 2:
            continue
        group_id += 1
        for path in sorted(members):
            e = path_to_entry.get(path, {})
            result.append({
                "group_id": group_id,
                "phash": e.get("phash", ""),
                "file_path": path,
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
    try:
        cursor = conn.execute("""
            SELECT file_path, exif_datetime, subsec_time, phash, extension
            FROM photos
            WHERE exif_datetime != '' AND exif_datetime IS NOT NULL
            AND subsec_time != '' AND subsec_time IS NOT NULL
            AND media_type = 'image'
            ORDER BY exif_datetime, subsec_time
        """)
    except sqlite3.OperationalError as e:
        conn.close()
        print(f"  ⚠️  Burst detection requires EXIF metadata (exif_datetime, subsec_time): {e}", file=sys.stderr)
        return []
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
# Mode 5: CNN deep learning dedup (MobileNet-V3 / ResNet feature extraction)
# ---------------------------------------------------------------------------

# Feature vector dimension for MobileNet-V3
CNN_FEATURE_DIM = 1024 if TORCH_AVAILABLE else 0

# Lazy-loaded model
_cnn_model = None
_cnn_transform = None
_onnx_session = None


def _get_cnn_model():
    """Lazy-load MobileNet-V3 model for feature extraction."""
    global _cnn_model, _cnn_transform

    if _cnn_model is not None:
        return _cnn_model, _cnn_transform

    if not TORCH_AVAILABLE:
        return None, None

    try:
        # Use MobileNet-V3 Small for efficiency (4.2MB vs 21MB for Large)
        model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
        model.eval()

        # Remove the classifier head — we only need features
        # The last linear layer is at model.classifier[3]
        # Feature output from avgpool is 576-dim for Small
        feature_extractor = torch.nn.Sequential(
            model.features,
            model.avgpool,
            torch.nn.Flatten(),
        )
        feature_extractor.eval()

        # Standard ImageNet preprocessing
        transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225]),
        ])

        _cnn_model = feature_extractor
        _cnn_transform = transform
        return _cnn_model, _cnn_transform

    except Exception as e:
        print(f"  ⚠️  Failed to load MobileNet-V3: {e}", file=sys.stderr)
        return None, None


def _get_onnx_session():
    """Lazy-load ONNX Runtime session for MobileNet-V3 feature extraction."""
    global _onnx_session

    if _onnx_session is not None:
        return _onnx_session

    if not ONNX_AVAILABLE or not PIL_AVAILABLE:
        return None

    # ONNX model path — check common locations
    onnx_paths = [
        os.path.expanduser("~/.snaptidy/models/mobilenetv3_small.onnx"),
        os.path.join(os.path.dirname(__file__), "models", "mobilenetv3_small.onnx"),
    ]

    onnx_path = None
    for p in onnx_paths:
        if os.path.exists(p):
            onnx_path = p
            break

    if not onnx_path:
        return None

    try:
        sess = ort.InferenceSession(onnx_path,
                                     providers=["CPUExecutionProvider"])
        _onnx_session = sess
        return _onnx_session
    except Exception as e:
        print(f"  ⚠️  Failed to load ONNX model: {e}", file=sys.stderr)
        return None


def _extract_feature_pytorch(image_path: str) -> list:
    """Extract feature vector from an image using PyTorch MobileNet-V3.

    Returns 576-dim feature vector (MobileNet-V3 Small) or empty list on error.
    """
    model, transform = _get_cnn_model()
    if model is None or transform is None:
        return []

    try:
        img = PILImage.open(image_path).convert("RGB")
        tensor = transform(img).unsqueeze(0)  # [1, 3, 224, 224]

        with torch.no_grad():
            features = model(tensor)  # [1, 576]

        # Normalize the feature vector
        vec = features.squeeze(0).numpy().tolist()
        mag = math.sqrt(sum(v * v for v in vec))
        if mag > 0:
            vec = [v / mag for v in vec]
        return vec

    except Exception:
        return []


def _extract_feature_onnx(image_path: str) -> list:
    """Extract feature vector from an image using ONNX Runtime.

    Returns feature vector or empty list on error.
    """
    session = _get_onnx_session()
    if session is None:
        return []

    try:
        import numpy as _np

        img = PILImage.open(image_path).convert("RGB")
        img = img.resize((224, 224), PILImage.LANCZOS)

        # Convert to NCHW format with ImageNet normalization
        arr = _np.array(img, dtype=_np.float32) / 255.0
        arr = (arr - _np.array([0.485, 0.456, 0.406])) / _np.array([0.229, 0.224, 0.225])
        arr = arr.transpose(2, 0, 1)  # HWC -> CHW
        arr = arr[np.newaxis, ...]  # Add batch dimension

        input_name = session.get_inputs()[0].name
        output = session.run(None, {input_name: arr.astype(_np.float32)})

        vec = output[0].flatten().tolist()
        mag = math.sqrt(sum(v * v for v in vec))
        if mag > 0:
            vec = [v / mag for v in vec]
        return vec

    except Exception:
        return []


def _extract_feature(image_path: str) -> list:
    """Extract CNN feature vector, trying PyTorch first, then ONNX.

    Returns normalized feature vector or empty list on error.
    """
    if TORCH_AVAILABLE:
        return _extract_feature_pytorch(image_path)
    elif ONNX_AVAILABLE:
        return _extract_feature_onnx(image_path)
    return []


def detect_cnn_similar_db(index_path: str, threshold: float = 0.90,
                          batch_size: int = 32) -> list:
    """Detect similar photos using CNN deep learning feature extraction.

    Uses MobileNet-V3 (PyTorch) or ONNX Runtime for feature extraction,
    with cosine similarity for matching. Falls back gracefully if neither
    is available.

    Args:
        index_path: Path to SQLite metadata index
        threshold: Cosine similarity threshold (0.0-1.0, default 0.90)
        batch_size: Number of images to process per batch (default: 32)
    """
    # Check available backends
    backend = None
    if TORCH_AVAILABLE:
        backend = "pytorch"
    elif ONNX_AVAILABLE:
        backend = "onnx"
    else:
        print("  ⚠️  Neither PyTorch nor ONNX Runtime installed — CNN detection skipped", file=sys.stderr)
        print("     Install with: pip install torch torchvision  OR  pip install onnxruntime", file=sys.stderr)
        return []

    if not PIL_AVAILABLE:
        print("  ⚠️  Pillow not installed — CNN detection skipped", file=sys.stderr)
        return []

    print(f"  CNN dedup backend: {backend}")

    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Check available columns for cross-compatibility
    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    select_fields = ["file_path"]
    if "extension" in available_cols:
        select_fields.append("extension")
    if "media_type" in available_cols:
        select_fields.append("media_type")

    query = f"SELECT {', '.join(select_fields)} FROM photos"
    conditions = []
    if "media_type" in available_cols:
        conditions.append("media_type = 'image'")
    if "extension" in available_cols:
        conditions.append("extension IN ('jpg', 'jpeg', 'png', 'heic', 'heif', 'bmp', 'tif', 'tiff', 'webp')")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor = conn.execute(query)

    entries = []
    for row in cursor:
        row_dict = dict(row)
        entries.append({
            "path": row_dict["file_path"],
            "extension": row_dict.get("extension", ""),
        })
    conn.close()

    if len(entries) < 2:
        return []

    print(f"  Extracting CNN features for {len(entries)} images...")

    # Extract features with progress
    features = []  # [(path, feature_vector)]
    last_pct = -1

    for idx, entry in enumerate(entries):
        pct = idx * 100 // len(entries)
        if pct >= last_pct + 10 or idx == 0:
            print(f"  Extracting... {idx}/{len(entries)} ({pct}%)")
            last_pct = pct

        vec = _extract_feature(entry["path"])
        if vec:
            features.append((entry["path"], vec))

    print(f"  Extracted features: {len(features)}/{len(entries)} images")

    if len(features) < 2:
        return []

    # Union-Find for proper group merging
    parent = {}

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
    for i in range(len(features)):
        path1, vec1 = features[i]
        parent.setdefault(path1, path1)

        for j in range(i + 1, len(features)):
            path2, vec2 = features[j]
            parent.setdefault(path2, path2)

            # Cosine similarity (vectors already normalized)
            dot = sum(a * b for a, b in zip(vec1, vec2))
            if dot >= threshold:
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
                "match_type": "cnn_mobilenet",
            })

    return result


# ---------------------------------------------------------------------------
# Combined mode: run all detection methods
# ---------------------------------------------------------------------------

def detect_all_db(index_path: str, phash_threshold: int = 0,
                  cnn_threshold: float = 0.90, apple_ql_threshold: float = 0.92) -> list:
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

    # Apple quality vector similarity
    apple_ql_results = detect_apple_quality_similar_db(index_path, threshold=apple_ql_threshold)
    all_results.extend(apple_ql_results)

    # CNN deep learning similarity
    if TORCH_AVAILABLE or ONNX_AVAILABLE:
        cnn_results = detect_cnn_similar_db(index_path, threshold=cnn_threshold)
        all_results.extend(cnn_results)

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

    # Check if the required column exists
    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
    if "photos_quality_vector" not in available_cols:
        conn.close()
        return []

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
        "cnn_mobilenet": "CNN (MobileNet) similar",
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
    parser.add_argument("--detect-cnn", action="store_true",
                        help="Detect similar photos using CNN deep learning (MobileNet-V3, requires PyTorch or ONNX Runtime)")
    parser.add_argument("--detect-all", action="store_true",
                        help="Run all detection methods (pHash + scaled + cross-format + bursts + Apple QL + CNN)")
    parser.add_argument("--apple-ql-threshold", type=float, default=0.92,
                        help="Cosine similarity threshold for Apple quality vector detection (default: 0.92)")
    parser.add_argument("--cnn-threshold", type=float, default=0.90,
                        help="Cosine similarity threshold for CNN detection (default: 0.90)")
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
    run_phash = not (args.detect_scaled or args.detect_cross_format or args.detect_bursts or args.detect_apple_ql or args.detect_cnn) or run_all
    run_scaled = args.detect_scaled or run_all
    run_cross = args.detect_cross_format or run_all
    run_bursts = args.detect_bursts or run_all
    run_apple_ql = args.detect_apple_ql or run_all
    run_cnn = args.detect_cnn or run_all

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

    if run_cnn:
        cnn_results = detect_cnn_similar_db(index_path, threshold=args.cnn_threshold)
        all_results.extend(cnn_results)
        n = len(set(e["group_id"] for e in cnn_results)) if cnn_results else 0
        method_stats["CNN"] = (len(cnn_results), n)

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
