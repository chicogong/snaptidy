#!/usr/bin/env python3
"""Find perceptually identical images based on average hash.

This script reads the metadata index from `scan_photos.py` and groups entries
with the same perceptual hash value.  It is conservative: only identical
hashes are considered similar.  For more nuanced similarity detection, one
could compute Hamming distances or use embeddings.
"""

import argparse
import csv
import os
import sys


def group_by_phash(index_path: str):
    groups = {}
    with open(index_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ph = row.get("phash", "")
            if ph:
                groups.setdefault(ph, []).append(row.get("file_path"))
    # Only keep groups with more than one member
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
    parser = argparse.ArgumentParser(description="Find perceptually identical images by average hash")
    parser.add_argument("--index", required=True, help="Path to metadata CSV (photo_index.csv)")
    parser.add_argument("--output", required=True, help="Path to output CSV for similar images")
    args = parser.parse_args()
    index_path = os.path.abspath(args.index)
    output_path = os.path.abspath(args.output)
    entries = group_by_phash(index_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_csv(entries, output_path)
    print(f"Found {len(entries)} images in {len(set([e['group_id'] for e in entries]))} perceptual groups.")


if __name__ == "__main__":
    main()