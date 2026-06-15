#!/usr/bin/env python3
"""Find perceptually identical images based on average hash.

Reads the metadata index (SQLite DB or CSV) and groups entries
with the same perceptual hash value.  Conservative: only identical
hashes are grouped.  For fuzzy matching, use --threshold for Hamming distance.
"""

import argparse
import csv
import os
import sqlite3
import sys

try:
    import imagehash
except ImportError:
    print("imagehash is required. Install with: pip install imagehash", file=sys.stderr)
    sys.exit(1)


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
                result.append({"group_id": group_id, "phash": ph, "file_path": p})
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
                result.append({"group_id": gid, "phash": ph, "file_path": p})
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
                result.append({"group_id": group_id, "phash": ph, "file_path": p})
    return result


def write_csv(entries, output_path):
    fieldnames = ["group_id", "phash", "file_path"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find perceptually identical images by average hash")
    parser.add_argument("--index", required=True, help="Path to metadata index (.db or .csv)")
    parser.add_argument("--output", required=True, help="Path to output CSV for similar images")
    parser.add_argument("--threshold", type=int, default=0,
                        help="Hamming distance threshold for fuzzy matching (0=exact, default: 0)")
    args = parser.parse_args()
    index_path = os.path.abspath(args.index)
    output_path = os.path.abspath(args.output)

    if index_path.endswith(".db"):
        entries = group_by_phash_db(index_path, threshold=args.threshold)
    else:
        entries = group_by_phash_csv(index_path)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_csv(entries, output_path)

    num_groups = len(set(e["group_id"] for e in entries)) if entries else 0
    print(f"Found {len(entries)} images in {num_groups} perceptual groups.")


if __name__ == "__main__":
    main()
