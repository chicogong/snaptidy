#!/usr/bin/env python3
"""Compare Photos.app library vs file-system folder — find unique and shared photos.

Useful for:
  - Finding photos only in your Photos.app (not backed up to disk)
  - Finding photos only on disk (not imported to Photos.app)
  - Identifying shared/overlapping photos

Comparison methods:
  1. SHA-256 exact match (definitive — same file content)
  2. Filename match (approximate — same name may differ in content)

Usage:
    # Compare Photos.app library against a file-system folder
    python3 scripts/compare_libraries.py \
        --library ~/Pictures/Photos\ Library.photoslibrary \
        --folder ~/Pictures/Export \
        --output comparison.json

    # CSV output
    python3 scripts/compare_libraries.py \
        --library ~/Pictures/Photos\ Library.photoslibrary \
        --folder ~/Pictures/Export \
        --output comparison.csv

    # Only show unique items (not shared)
    python3 scripts/compare_libraries.py \
        --library ~/Pictures/Photos\ Library.photoslibrary \
        --folder ~/Pictures/Export \
        --output comparison.csv --unique-only
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict

from constants import IMAGE_EXTS, VIDEO_EXTS, format_size


def load_library_hashes(library_path: str) -> dict:
    """Load SHA-256 hashes from Photos.app library via Photos.sqlite.

    Returns: {sha256: [file_path, ...]}
    """
    db_path = os.path.join(library_path, "database", "Photos.sqlite")
    if not os.path.exists(db_path):
        print(f"Error: Photos.sqlite not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    # Copy DB to avoid locking issues
    import tempfile
    import shutil
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    shutil.copy2(db_path, tmp.name)

    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row

    hashes = defaultdict(list)

    try:
        # Get ZASSET → file path + SHA-256
        cursor = conn.execute("""
            SELECT
                ZASSET.Z_PK,
                ZASSET.ZFILENAME,
                ZADDITIONALASSETATTRIBUTES.ZSHA256HASH
            FROM ZASSET
            JOIN ZADDITIONALASSETATTRIBUTES
                ON ZASSET.Z_PK = ZADDITIONALASSETATTRIBUTES.Z_PK
            WHERE ZASSET.ZTRASHSTATE = 0
              AND ZADDITIONALASSETATTRIBUTES.ZSHA256HASH IS NOT NULL
        """)

        for row in cursor:
            sha256 = row["ZSHA256HASH"]
            filename = row["ZFILENAME"] or ""
            if sha256:
                # Convert binary hash to hex if needed
                if isinstance(sha256, bytes):
                    sha256 = sha256.hex()
                hashes[sha256].append({
                    "source": "library",
                    "filename": filename,
                    "pk": row["Z_PK"],
                })
    except sqlite3.OperationalError:
        # Fallback: try without SHA-256 (use filename matching only)
        print("  Warning: SHA-256 not available in library, using filename matching", file=sys.stderr)
    finally:
        conn.close()
        os.unlink(tmp.name)

    return dict(hashes)


def load_library_filenames(library_path: str) -> dict:
    """Load filenames from Photos.app library.

    Returns: {filename_lower: [pk, ...]}
    """
    db_path = os.path.join(library_path, "database", "Photos.sqlite")
    import tempfile, shutil
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    shutil.copy2(db_path, tmp.name)

    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row

    filenames = defaultdict(list)

    try:
        cursor = conn.execute("""
            SELECT Z_PK, ZFILENAME FROM ZASSET WHERE ZTRASHSTATE = 0
        """)
        for row in cursor:
            fn = (row["ZFILENAME"] or "").lower()
            if fn:
                filenames[fn].append(row["Z_PK"])
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
        os.unlink(tmp.name)

    return dict(filenames)


def load_folder_index(index_path: str) -> tuple:
    """Load SHA-256 and filenames from file-system index DB.

    Returns: (hashes: {sha256: [path, ...]}, filenames: {name_lower: [path, ...]})
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    hashes = defaultdict(list)
    filenames = defaultdict(list)

    cursor = conn.execute("SELECT file_path, filename, sha256 FROM photos")
    for row in cursor:
        path = row["file_path"]
        fn = (row["filename"] or "").lower()
        sha = row["sha256"] or ""

        if sha:
            hashes[sha].append({"source": "folder", "path": path, "filename": row["filename"]})
        if fn:
            filenames[fn].append(path)

    conn.close()
    return dict(hashes), dict(filenames)


def compare_libraries(library_path: str, index_path: str, unique_only: bool = False) -> dict:
    """Compare Photos.app library against file-system index.

    Returns comparison dict.
    """
    print("📂 Loading Photos.app library...")
    lib_hashes = load_library_hashes(library_path)
    lib_filenames = load_library_filenames(library_path)

    print("📁 Loading file-system index...")
    folder_hashes, folder_filenames = load_folder_index(index_path)

    print("🔍 Comparing...")

    # SHA-256 comparison
    shared_by_hash = []
    lib_only_by_hash = []
    folder_only_by_hash = []

    all_hashes = set(lib_hashes.keys()) | set(folder_hashes.keys())
    for sha in all_hashes:
        in_lib = sha in lib_hashes
        in_folder = sha in folder_hashes

        if in_lib and in_folder:
            shared_by_hash.append({
                "sha256": sha,
                "library_items": lib_hashes[sha],
                "folder_items": folder_hashes[sha],
            })
        elif in_lib:
            lib_only_by_hash.append({
                "sha256": sha,
                "items": lib_hashes[sha],
            })
        else:
            folder_only_by_hash.append({
                "sha256": sha,
                "items": folder_hashes[sha],
            })

    # Filename comparison (supplementary — catches files with same name but different content)
    shared_by_name = []
    lib_only_by_name = []
    folder_only_by_name = []

    all_names = set(lib_filenames.keys()) | set(folder_filenames.keys())
    for name in all_names:
        in_lib = name in lib_filenames
        in_folder = name in folder_filenames

        if in_lib and in_folder:
            shared_by_name.append(name)
        elif in_lib:
            lib_only_by_name.append(name)
        else:
            folder_only_by_name.append(name)

    return {
        "by_sha256": {
            "shared": shared_by_hash,
            "library_only": lib_only_by_hash,
            "folder_only": folder_only_by_hash,
        },
        "by_filename": {
            "shared": shared_by_name,
            "library_only": lib_only_by_name,
            "folder_only": folder_only_by_name,
        },
        "summary": {
            "library_total_hashes": len(lib_hashes),
            "folder_total_hashes": len(folder_hashes),
            "shared_by_hash": len(shared_by_hash),
            "library_only_by_hash": len(lib_only_by_hash),
            "folder_only_by_hash": len(folder_only_by_hash),
            "shared_by_name": len(shared_by_name),
            "library_only_by_name": len(lib_only_by_name),
            "folder_only_by_name": len(folder_only_by_name),
        },
    }


def write_report(results: dict, output_path: str, unique_only: bool = False) -> None:
    """Write comparison report to JSON or CSV."""
    ext = output_path.rsplit(".", 1)[-1].lower() if "." in output_path else "json"

    if ext == "json":
        out = results
        if unique_only:
            out = {
                "library_only_by_hash": results["by_sha256"]["library_only"],
                "folder_only_by_hash": results["by_sha256"]["folder_only"],
                "summary": results["summary"],
            }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    else:
        rows = []
        for item in results["by_sha256"]["shared"]:
            for lib in item["library_items"]:
                rows.append({"status": "shared", "source": "library", "sha256": item["sha256"],
                             "filename": lib.get("filename", "")})
            for fol in item["folder_items"]:
                rows.append({"status": "shared", "source": "folder", "sha256": item["sha256"],
                             "filename": fol.get("filename", ""), "path": fol.get("path", "")})

        if not unique_only:
            for item in results["by_sha256"]["library_only"]:
                for lib in item["items"]:
                    rows.append({"status": "library_only", "source": "library", "sha256": item["sha256"],
                                 "filename": lib.get("filename", "")})
            for item in results["by_sha256"]["folder_only"]:
                for fol in item["items"]:
                    rows.append({"status": "folder_only", "source": "folder", "sha256": item["sha256"],
                                 "filename": fol.get("filename", ""), "path": fol.get("path", "")})
        else:
            for item in results["by_sha256"]["library_only"]:
                for lib in item["items"]:
                    rows.append({"status": "library_only", "source": "library", "sha256": item["sha256"],
                                 "filename": lib.get("filename", "")})
            for item in results["by_sha256"]["folder_only"]:
                for fol in item["items"]:
                    rows.append({"status": "folder_only", "source": "folder", "sha256": item["sha256"],
                                 "filename": fol.get("filename", ""), "path": fol.get("path", "")})

        if rows:
            fieldnames = list(rows[0].keys())
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Photos.app library vs file-system folder")
    parser.add_argument("--library", "-l", dest="library", required=True,
                        help="Path to .photoslibrary bundle")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to file-system index DB")
    parser.add_argument("--output", "-o", dest="output", required=True,
                        help="Output report path (.json or .csv)")
    parser.add_argument("--unique-only", action="store_true",
                        help="Only show items unique to each source (not shared)")
    args = parser.parse_args()

    library_path = os.path.abspath(args.library)
    index_path = os.path.abspath(args.index)

    if not os.path.exists(library_path):
        print(f"Error: Library not found: {library_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(index_path):
        print(f"Error: Index not found: {index_path}", file=sys.stderr)
        sys.exit(1)

    results = compare_libraries(library_path, index_path, unique_only=args.unique_only)
    write_report(results, os.path.abspath(args.output), unique_only=args.unique_only)

    s = results["summary"]
    print(f"\n{'=' * 50}")
    print(f"Library Comparison Report")
    print(f"  Library photos (by hash): {s['library_total_hashes']}")
    print(f"  Folder photos (by hash):  {s['folder_total_hashes']}")
    print(f"  Shared (both):            {s['shared_by_hash']}")
    print(f"  Library only:             {s['library_only_by_hash']}")
    print(f"  Folder only:              {s['folder_only_by_hash']}")
    print(f"\n  Report saved: {args.output}")


if __name__ == "__main__":
    main()
