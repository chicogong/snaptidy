#!/usr/bin/env python3
"""Find exact duplicate files based on SHA‑256.

Reads the metadata index (SQLite DB or CSV) and groups files with
identical SHA‑256 hashes.  Outputs a CSV where each row represents a duplicate
file, with a group identifier and the shared hash.  Groups of size one are
omitted.

When using SQLite, queries are efficient (indexed) even for 100k+ photos.
"""

import argparse
import csv
import os
import sqlite3
import sys


def find_duplicates_db(index_path: str) -> list:
    """Find duplicates from SQLite database (fast, indexed)."""
    conn = sqlite3.connect(index_path)
    cursor = conn.execute("""
        SELECT sha256, file_path FROM photos
        WHERE sha256 IN (
            SELECT sha256 FROM photos
            GROUP BY sha256
            HAVING COUNT(*) > 1
        )
        ORDER BY sha256, file_path
    """)
    groups = {}
    for sha, path in cursor:
        groups.setdefault(sha, []).append(path)
    conn.close()

    duplicates = []
    group_id = 0
    for sha, paths in groups.items():
        group_id += 1
        for p in paths:
            duplicates.append({"group_id": group_id, "sha256": sha, "file_path": p})
    return duplicates


def find_duplicates_csv(index_path: str) -> list:
    """Find duplicates from CSV file (fallback)."""
    groups = {}
    with open(index_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sha = row.get("sha256", "")
            if not sha:
                continue
            groups.setdefault(sha, []).append(row.get("file_path"))

    duplicates = []
    group_id = 0
    for sha, paths in groups.items():
        if len(paths) > 1:
            group_id += 1
            for p in paths:
                duplicates.append({"group_id": group_id, "sha256": sha, "file_path": p})
    return duplicates


def write_duplicates(dups: list, output_path: str) -> None:
    fieldnames = ["group_id", "sha256", "file_path"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in dups:
            writer.writerow(entry)


def main() -> None:
    parser = argparse.ArgumentParser(description="Find exact duplicate files by SHA‑256")
    parser.add_argument("--index", required=True, help="Path to metadata index (.db or .csv)")
    parser.add_argument("--output", required=True, help="Path to output duplicates CSV")
    args = parser.parse_args()
    index_path = os.path.abspath(args.index)
    output_path = os.path.abspath(args.output)

    if index_path.endswith(".db"):
        duplicates = find_duplicates_db(index_path)
    else:
        duplicates = find_duplicates_csv(index_path)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_duplicates(duplicates, output_path)

    num_groups = len(set(d["group_id"] for d in duplicates)) if duplicates else 0
    print(f"Found {len(duplicates)} duplicate files across {num_groups} groups.")


if __name__ == "__main__":
    main()
