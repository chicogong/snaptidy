#!/usr/bin/env python3
"""Find exact duplicate files based on SHA‑256.

Reads the metadata CSV produced by `scan_photos.py` and groups files with
identical SHA‑256 hashes.  Outputs a CSV where each row represents a duplicate
file, with a group identifier and the shared hash.  Groups of size one are
omitted.
"""

import argparse
import csv
import os
import sys


def find_duplicates(index_path: str) -> list:
    """Return a list of duplicate entries.  Each entry is (group_id, sha256, path)."""
    duplicates = []
    groups = {}
    with open(index_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sha = row.get("sha256", "")
            if not sha:
                continue
            groups.setdefault(sha, []).append(row.get("file_path"))
    group_id = 0
    for sha, paths in groups.items():
        if len(paths) > 1:
            group_id += 1
            for p in paths:
                duplicates.append({"group_id": group_id, "sha256": sha, "file_path": p})
    return duplicates


def write_duplicates(dups: list, output_path: str) -> None:
    fieldnames = ["group_id", "sha256", "file_path"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in dups:
            writer.writerow(entry)


def main() -> None:
    parser = argparse.ArgumentParser(description="Find exact duplicate files by SHA‑256")
    parser.add_argument("--index", required=True, help="Path to metadata CSV (photo_index.csv)")
    parser.add_argument("--output", required=True, help="Path to output duplicates CSV")
    args = parser.parse_args()
    index_path = os.path.abspath(args.index)
    output_path = os.path.abspath(args.output)
    duplicates = find_duplicates(index_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_duplicates(duplicates, output_path)
    print(f"Found {len(duplicates)} duplicate files across {len(set([d['group_id'] for d in duplicates]))} groups.")


if __name__ == "__main__":
    main()