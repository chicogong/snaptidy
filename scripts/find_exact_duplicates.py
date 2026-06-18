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

from constants import format_size


def find_duplicates_db(index_path: str, include_icloud: bool = True) -> tuple:
    """Find duplicates from SQLite database (fast, indexed).

    Returns (duplicates_list, group_meta_dict).

    Args:
        include_icloud: if False, skip files marked as iCloud placeholders
                        (their SHA-256 is unreliable for dedup)
    """
    conn = sqlite3.connect(index_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)").fetchall()}

    icloud_filter = ""
    if not include_icloud and "icloud_state" in cols:
        icloud_filter = " AND icloud_state NOT IN ('icloud_placeholder', 'download_failed')"

    cursor = conn.execute(f"""
        SELECT sha256, file_path, size_bytes, category, format_family
        FROM photos
        WHERE sha256 IN (
            SELECT sha256 FROM photos
            WHERE 1=1 {icloud_filter}
            GROUP BY sha256
            HAVING COUNT(*) > 1
        )
        {icloud_filter}
        ORDER BY sha256, file_path
    """)
    groups = {}
    group_meta = {}  # sha256 -> [{path, size, category, format}]
    for sha, path, size, cat, fmt in cursor:
        groups.setdefault(sha, []).append(path)
        group_meta.setdefault(sha, []).append({
            "path": path, "size": size or 0, "category": cat or "", "format": fmt or ""
        })
    conn.close()

    duplicates = []
    group_id = 0
    for sha, paths in groups.items():
        group_id += 1
        for p in paths:
            duplicates.append({"group_id": group_id, "sha256": sha, "file_path": p})

    return duplicates, group_meta


def find_duplicates_csv(index_path: str) -> tuple:
    """Find duplicates from CSV file (fallback).

    Returns (duplicates_list, group_meta_dict).
    """
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
    return duplicates, {}


def write_duplicates(dups: list, output_path: str) -> None:
    fieldnames = ["group_id", "sha256", "file_path"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in dups:
            writer.writerow(entry)


def write_human(dups: list, output_path: str, group_meta: dict = None) -> None:
    """Write human-readable duplicate report."""
    group_meta = group_meta or {}
    # Group by group_id
    groups = {}
    for d in dups:
        groups.setdefault(d["group_id"], []).append(d)

    lines = []
    lines.append("=" * 72)
    lines.append(f"Exact Duplicates Report — {len(dups)} files in {len(groups)} groups")
    lines.append("=" * 72)
    lines.append("")

    total_waste = 0
    for gid in sorted(groups.keys()):
        entries = groups[gid]
        sha = entries[0]["sha256"][:16] + "..."
        # Calculate wasted space (n-1 copies)
        waste = 0
        file_details = []
        for e in entries:
            # Try to get size from group_meta
            meta = group_meta.get(entries[0]["sha256"], [])
            size = 0
            for m in meta:
                if m["path"] == e["file_path"]:
                    size = m["size"]
                    break
            waste += size
            # Shorten path for readability
            path = e["file_path"]
            if len(path) > 60:
                path = "..." + path[-57:]
            file_details.append(f"    {format_size(size):>10}  {path}")

        waste = waste // len(entries) * (len(entries) - 1) if entries else 0  # n-1 copies waste
        total_waste += waste

        lines.append(f"Group {gid} ({len(entries)} files, {sha})")
        lines.extend(file_details)
        lines.append(f"    Wasted: {format_size(waste)}")
        lines.append("")

    lines.append("-" * 72)
    lines.append(f"Total wasted space: {format_size(total_waste)}")
    lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Find exact duplicate files by SHA‑256")
    parser.add_argument("--index", "-i", dest="index", required=True, help="Path to metadata index (.db or .csv)")
    parser.add_argument("--output", "-o", dest="output", required=True, help="Path to output duplicates CSV")
    parser.add_argument("--format", choices=["csv", "human"], default="csv",
                        help="Output format: csv (default) or human (readable report)")
    parser.add_argument("--exclude-icloud", action="store_true",
                        help="Exclude iCloud placeholder files (their SHA-256 is unreliable for dedup)")
    args = parser.parse_args()
    index_path = os.path.abspath(args.index)
    output_path = os.path.abspath(args.output)

    if index_path.endswith(".db"):
        duplicates, group_meta = find_duplicates_db(index_path, include_icloud=not args.exclude_icloud)
    else:
        duplicates, group_meta = find_duplicates_csv(index_path)

    os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None

    if args.format == "human":
        write_human(duplicates, output_path, group_meta)
    else:
        write_duplicates(duplicates, output_path)

    num_groups = len(set(d["group_id"] for d in duplicates)) if duplicates else 0
    print(f"Found {len(duplicates)} duplicate files across {num_groups} groups.")
    if args.exclude_icloud:
        print("  (iCloud placeholder files excluded)")


if __name__ == "__main__":
    main()
