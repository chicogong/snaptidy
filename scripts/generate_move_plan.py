#!/usr/bin/env python3
"""Generate a move plan for duplicates.

This script reads the metadata index and a duplicates CSV (from
`find_exact_duplicates.py`) and proposes moves for duplicate files into a
specified directory tree.  The first file in each duplicate group is kept in
place; all subsequent files are moved into a `06_Duplicates_待确认删除` folder
under the given target root, preserving their relative paths.  The output is a
CSV with columns: action, source_path, target_path, reason.
"""

import argparse
import csv
import os
import sys


def read_duplicates(dups_path: str):
    groups = {}
    with open(dups_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gid = row.get("group_id")
            groups.setdefault(gid, []).append(row.get("file_path"))
    return groups


def generate_plan(groups: dict, target_root: str) -> list:
    plan = []
    for group_id, paths in groups.items():
        if len(paths) < 2:
            continue
        # keep the first file (lowest sort order) in place
        sorted_paths = sorted(paths)
        keep = sorted_paths[0]
        for path in sorted_paths[1:]:
            # compute relative path to target root
            try:
                rel = os.path.relpath(path, target_root)
            except ValueError:
                # path is on different mount; just use filename
                rel = os.path.basename(path)
            dest = os.path.join(target_root, "06_Duplicates_待确认删除", rel)
            plan.append({
                "action": "move",
                "source_path": path,
                "target_path": dest,
                "reason": f"exact duplicate of {keep}",
            })
    return plan


def write_plan(plan, plan_path: str) -> None:
    fieldnames = ["action", "source_path", "target_path", "reason"]
    with open(plan_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in plan:
            writer.writerow(entry)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate move plan for duplicates")
    parser.add_argument("--duplicates", required=True, help="Path to duplicates_exact.csv")
    parser.add_argument("--plan", required=True, help="Path to output move plan CSV")
    parser.add_argument("--target-root", required=True, help="Root of your photo archive")
    args = parser.parse_args()
    dups = read_duplicates(os.path.abspath(args.duplicates))
    target_root = os.path.abspath(args.target_root)
    plan = generate_plan(dups, target_root)
    os.makedirs(os.path.dirname(os.path.abspath(args.plan)), exist_ok=True)
    write_plan(plan, os.path.abspath(args.plan))
    print(f"Generated move plan with {len(plan)} actions.")


if __name__ == "__main__":
    main()