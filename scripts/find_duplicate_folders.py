#!/usr/bin/env python3
"""Find duplicate or similar folders based on file content.

Identifies folders that are complete or near-complete duplicates of each other
by comparing the SHA-256 hashes of their contents. Useful for finding redundant
backup copies.

Algorithm:
  1. Group all files by SHA-256 hash (from index DB or computed on-the-fly)
  2. For each folder, build a set of file hashes
  3. Compare folder pairs by Jaccard similarity (intersection / union)
  4. Group folders with similarity >= threshold

Usage:
  python find_duplicate_folders.py --source ~/Photos [--threshold 0.7] [--report dup_folders.csv]
  python find_duplicate_folders.py --index photo_index.db [--threshold 0.5]
"""

import argparse
import csv
import os
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from constants import PHOTO_EXTENSIONS, format_size


def build_folder_index_from_db(index_path: str) -> dict:
    """Build folder → {hashes, files, total_size} from existing index DB.

    Returns: {folder_path: {"hashes": set, "files": list, "total_size": int}}
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT file_path, sha256, size_bytes FROM photos WHERE sha256 IS NOT NULL AND sha256 != ''"
    ).fetchall()
    conn.close()

    folders = defaultdict(lambda: {"hashes": set(), "files": [], "total_size": 0})

    for row in rows:
        fp = row["file_path"]
        sha256 = row["sha256"]
        size = row["size_bytes"] or 0
        folder = str(Path(fp).parent)

        folders[folder]["hashes"].add(sha256)
        folders[folder]["files"].append(fp)
        folders[folder]["total_size"] += size

    return dict(folders)


def build_folder_index_from_fs(source: str) -> dict:
    """Build folder → {hashes, files, total_size} by scanning filesystem.

    Computes SHA-256 for each file. Slower but works without an index DB.
    """
    import hashlib

    folders = defaultdict(lambda: {"hashes": set(), "files": [], "total_size": 0})
    total_files = 0
    source = os.path.abspath(source)

    for dirpath, _, filenames in os.walk(source):
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext not in PHOTO_EXTENSIONS:
                continue

            full_path = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue

            # Compute SHA-256
            h = hashlib.sha256()
            try:
                with open(full_path, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
                sha256 = h.hexdigest()
            except (OSError, PermissionError):
                continue

            folder = str(Path(full_path).parent)
            folders[folder]["hashes"].add(sha256)
            folders[folder]["files"].append(full_path)
            folders[folder]["total_size"] += size
            total_files += 1

            if total_files % 500 == 0:
                print(f"  Scanned {total_files} files...")

    return dict(folders)


# ---------------------------------------------------------------------------
# Folder similarity
# ---------------------------------------------------------------------------

def compute_jaccard(set_a: set, set_b: set) -> float:
    """Compute Jaccard similarity: |A ∩ B| / |A ∪ B|."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return intersection / union


def compute_overlap(set_a: set, set_b: set) -> tuple:
    """Compute overlap metrics between two sets.

    Returns: (jaccard, a_in_b_ratio, b_in_a_ratio)
      - jaccard: |A ∩ B| / |A ∪ B|
      - a_in_b_ratio: |A ∩ B| / |A| (how much of A is in B)
      - b_in_a_ratio: |A ∩ B| / |B| (how much of B is in A)
    """
    if not set_a or not set_b:
        return 0.0, 0.0, 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    jaccard = intersection / union if union > 0 else 0.0
    a_in_b = intersection / len(set_a) if len(set_a) > 0 else 0.0
    b_in_a = intersection / len(set_b) if len(set_b) > 0 else 0.0
    return jaccard, a_in_b, b_in_a


def find_similar_folders(folders: dict, threshold: float = 0.5,
                         min_files: int = 3) -> list:
    """Find folder pairs with similarity >= threshold.

    Optimized by pre-grouping folders that share at least one file hash.
    """
    # Build reverse index: hash → set of folders
    hash_to_folders = defaultdict(set)
    for folder, data in folders.items():
        if len(data["files"]) < min_files:
            continue  # Skip very small folders
        for h in data["hashes"]:
            hash_to_folders[h].add(folder)

    # Find candidate pairs (folders that share at least one hash)
    candidate_pairs = set()
    for h, folder_set in hash_to_folders.items():
        folder_list = sorted(folder_set)
        for i in range(len(folder_list)):
            for j in range(i + 1, len(folder_list)):
                candidate_pairs.add((folder_list[i], folder_list[j]))

    # Compute similarity for candidate pairs
    results = []
    for folder_a, folder_b in candidate_pairs:
        if folder_a not in folders or folder_b not in folders:
            continue

        hashes_a = folders[folder_a]["hashes"]
        hashes_b = folders[folder_b]["hashes"]

        jaccard, a_in_b, b_in_a = compute_overlap(hashes_a, hashes_b)

        if jaccard >= threshold:
            shared = len(hashes_a & hashes_b)
            results.append({
                "folder_a": folder_a,
                "folder_b": folder_b,
                "jaccard": round(jaccard, 3),
                "a_in_b": round(a_in_b, 3),
                "b_in_a": round(b_in_a, 3),
                "shared_files": shared,
                "folder_a_files": len(hashes_a),
                "folder_b_files": len(hashes_b),
                "folder_a_size": folders[folder_a]["total_size"],
                "folder_b_size": folders[folder_b]["total_size"],
            })

    # Sort by similarity (descending)
    results.sort(key=lambda x: x["jaccard"], reverse=True)
    return results


def group_duplicate_folders(similar_pairs: list, threshold: float = 0.9) -> list:
    """Group folders that are near-identical (>= threshold similarity).

    Uses union-find to cluster folders into groups.
    Returns list of groups, each group is a list of folder paths.
    """
    # Union-Find
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for pair in similar_pairs:
        if pair["jaccard"] >= threshold:
            union(pair["folder_a"], pair["folder_b"])

    # Collect groups
    groups = defaultdict(list)
    all_folders = set()
    for pair in similar_pairs:
        all_folders.add(pair["folder_a"])
        all_folders.add(pair["folder_b"])

    for folder in all_folders:
        groups[find(folder)].append(folder)

    return [sorted(g) for g in groups.values() if len(g) > 1]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(results: list, groups: list, report_path: str):
    """Write duplicate folder report to CSV."""
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["type", "folder_a", "folder_b", "jaccard",
                         "a_in_b", "b_in_a", "shared_files",
                         "folder_a_files", "folder_b_files",
                         "folder_a_size", "folder_b_size"])

        for r in results:
            writer.writerow([
                "pair", r["folder_a"], r["folder_b"], r["jaccard"],
                r["a_in_b"], r["b_in_a"], r["shared_files"],
                r["folder_a_files"], r["folder_b_files"],
                r["folder_a_size"], r["folder_b_size"],
            ])

        for i, group in enumerate(groups):
            for folder in group:
                writer.writerow([
                    f"group_{i+1}", folder, "", "", "", "", "", "", "", "", "",
                ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Find duplicate or similar folders based on file content",
    )
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--source", "-s", help="Source directory to scan")
    src_group.add_argument("--index", "-i", help="Path to SQLite index DB")
    parser.add_argument("--threshold", "-t", type=float, default=0.5,
                        help="Minimum Jaccard similarity threshold (default: 0.5)")
    parser.add_argument("--min-files", type=int, default=3,
                        help="Minimum files in a folder to consider (default: 3)")
    parser.add_argument("--report", "-o", default="", help="Output CSV report")
    args = parser.parse_args()

    print(f"📂 Finding duplicate folders (threshold: {args.threshold})...")
    start = time.time()

    # Build folder index
    if args.source:
        if not os.path.exists(args.source):
            print(f"Error: Source directory not found: {args.source}")
            sys.exit(1)
        print(f"  Scanning: {args.source}")
        folders = build_folder_index_from_fs(args.source)
    else:
        if not os.path.exists(args.index):
            print(f"Error: Index DB not found: {args.index}")
            sys.exit(1)
        print(f"  Loading index: {args.index}")
        folders = build_folder_index_from_db(args.index)

    elapsed_scan = time.time() - start
    total_files = sum(len(d["files"]) for d in folders.values())
    print(f"  {len(folders)} folders, {total_files} files (scan: {elapsed_scan:.1f}s)")

    if len(folders) < 2:
        print("  Not enough folders to compare.")
        return

    # Find similar folders
    print(f"  🔍 Comparing folder pairs...")
    results = find_similar_folders(folders, threshold=args.threshold,
                                   min_files=args.min_files)

    # Group near-duplicates (Jaccard >= 0.9)
    groups = group_duplicate_folders(results, threshold=0.9)

    elapsed = time.time() - start

    # Summary
    print(f"\n  ✅ Done in {elapsed:.1f}s")
    print(f"  📊 Similar folder pairs: {len(results)}")
    print(f"  📁 Near-duplicate groups (≥90%): {len(groups)}")

    if results:
        # Top 10 similar pairs
        print("\n  Top similar folders:")
        for r in results[:10]:
            print(f"    {r['jaccard']:.1%} — {r['folder_a']}")
            print(f"          vs {r['folder_b']}")
            print(f"          Shared: {r['shared_files']} files "
                  f"({r['a_in_b']:.0%} of A, {r['b_in_a']:.0%} of B)")

        if len(results) > 10:
            print(f"    ... and {len(results) - 10} more pairs")

    if groups:
        print("\n  Near-duplicate groups:")
        for i, group in enumerate(groups):
            total_size = sum(folders.get(f, {}).get("total_size", 0) for f in group)
            print(f"    Group {i + 1} ({len(group)} folders, {format_size(total_size)}):")
            for folder in group:
                n = len(folders[folder]["files"])
                print(f"      - {folder} ({n} files)")

    # Write report
    if args.report:
        write_report(results, groups, args.report)
        print(f"\n  Report → {args.report}")


if __name__ == "__main__":
    main()
