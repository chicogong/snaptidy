#!/usr/bin/env python3
"""Check and pre-download iCloud-only files before scanning.

When macOS "Optimize Storage" is enabled, iCloud offloads original photos
to the cloud and keeps only small thumbnails locally (2-50 KB).  These
thumbnails produce unreliable SHA-256 hashes and pHashes, causing false
negatives in duplicate detection and incorrect metadata.

This script scans a directory for iCloud placeholder files and can:
  1. Report how many files are iCloud-only and their total size
  2. Estimate the download size needed (originals are typically 10-50x larger)
  3. Batch download all iCloud files with progress reporting
  4. Verify that all files are now local before running downstream tools

Typical workflow:
    # Step 1: Check what needs downloading
    python3 check_icloud.py --source ~/Pictures/PhotoLibrary --report

    # Step 2: Download all iCloud files
    python3 check_icloud.py --source ~/Pictures/PhotoLibrary --download

    # Step 3: Scan with confidence (no --skip-icloud needed)
    python3 scan_photos.py -i ~/Pictures/PhotoLibrary -o index.db
"""

import argparse
import os
import sys
import time

from icloud_utils import (
    check_icloud_status,
    download_icloud_file,
    is_likely_thumbnail,
    scan_directory_for_icloud,
    THUMBNAIL_THRESHOLD_HEIC,
    THUMBNAIL_THRESHOLD_JPEG,
)
from constants import format_size


def print_report(icloud_files: list, source_dir: str) -> None:
    """Print a human-readable report of iCloud-only files."""
    total = len(icloud_files)
    if total == 0:
        print("\n  ✅ No iCloud placeholder files found — all files are local.")
        print(f"     Scanned directory: {source_dir}")
        return

    # Group by extension
    by_ext = {}
    by_reason = {}
    total_thumbnail_size = 0

    for f in icloud_files:
        ext = f["ext"] or "unknown"
        by_ext[ext] = by_ext.get(ext, 0) + 1

        reason = f["reason"]
        by_reason[reason] = by_reason.get(reason, 0) + 1

        total_thumbnail_size += f["size"]

    # Estimate original size (thumbnails are typically 10-50x smaller)
    estimated_original_size = total_thumbnail_size * 25  # conservative middle estimate

    print("\n" + "=" * 64)
    print("  ☁️  iCloud Placeholder Report")
    print("=" * 64)
    print(f"\n  📁 Source directory: {source_dir}")
    print(f"  📄 iCloud-only files: {total}")
    print(f"  💾 Current local size (thumbnails): {format_size(total_thumbnail_size)}")
    print(f"  📥 Estimated download size needed: {format_size(estimated_original_size)}")
    print(f"     (estimates originals are ~25x larger than thumbnails)")

    print(f"\n  📊 By format:")
    for ext, count in sorted(by_ext.items(), key=lambda x: -x[1]):
        print(f"     .{ext:8s} {count:>5} files")

    print(f"\n  🔍 Detection method:")
    reason_labels = {
        "companion_file": ".icloud companion file",
        "zero_byte": "zero-byte file",
        "thumbnail_heuristic": f"size heuristic (< {THUMBNAIL_THRESHOLD_HEIC // 1024}KB HEIC / < {THUMBNAIL_THRESHOLD_JPEG // 1024}KB JPEG)",
    }
    for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
        label = reason_labels.get(reason, reason)
        print(f"     {label:40s} {count:>5} files")

    print(f"\n  ⚠️  These files will produce unreliable results in:")
    print(f"     - Duplicate detection (SHA-256 differs from originals)")
    print(f"     - Similar photo detection (pHash differs from originals)")
    print(f"     - EXIF metadata extraction (may be missing or incomplete)")
    print(f"\n  💡 Recommended action:")
    print(f"     Run with --download to fetch originals from iCloud:")
    print(f"     python3 check_icloud.py --source \"{source_dir}\" --download")
    print()


def download_all(icloud_files: list, source_dir: str, dry_run: bool = False) -> None:
    """Download all iCloud placeholder files with progress reporting."""
    total = len(icloud_files)
    if total == 0:
        print("\n  ✅ No iCloud placeholder files to download.")
        return

    print(f"\n  📥 Downloading {total} iCloud files...")
    print(f"     This may take a while depending on your internet connection.\n")

    if dry_run:
        print("  [DRY RUN] Would download the following files:")
        for f in icloud_files[:20]:
            print(f"     {f['path']}")
        if total > 20:
            print(f"     ... and {total - 20} more")
        return

    downloaded = 0
    failed = 0
    skipped = 0
    start_time = time.monotonic()
    last_pct = -1

    for idx, f in enumerate(icloud_files):
        path = f["path"]

        # Check if already local (might have been downloaded by a previous run)
        status = check_icloud_status(path)
        if status == "local":
            skipped += 1
            continue

        # Show progress
        pct = (idx + 1) * 100 // total
        if pct >= last_pct + 5 or idx == 0:
            elapsed = time.monotonic() - start_time
            speed = (idx + 1) / elapsed if elapsed > 0 else 0
            remaining = (total - idx - 1) / speed if speed > 0 else 0
            print(f"  [{idx + 1}/{total}] ({pct}%) "
                  f"~{remaining:.0f}s remaining — {os.path.basename(path)}")
            last_pct = pct

        # Download
        success = download_icloud_file(path)
        if success:
            downloaded += 1
        else:
            failed += 1
            print(f"     ❌ Failed: {path}")

    elapsed = time.monotonic() - start_time
    print(f"\n  {'=' * 48}")
    print(f"  Download complete in {elapsed:.0f}s")
    print(f"  ✅ Downloaded: {downloaded}")
    print(f"  ⏭️  Skipped (already local): {skipped}")
    print(f"  ❌ Failed: {failed}")

    if failed > 0:
        print(f"\n  ⚠️  {failed} files could not be downloaded.")
        print(f"     They may not be available in iCloud, or iCloud sync is disabled.")
        print(f"     You can still scan with --skip-icloud to exclude them.")

    # Final verification
    remaining = scan_directory_for_icloud(source_dir)
    if remaining:
        print(f"\n  ⚠️  {len(remaining)} iCloud placeholder files still remain.")
    else:
        print(f"\n  ✅ All files are now local — ready for scanning!")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check and pre-download iCloud-only files before scanning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Typical workflow:
  1. Check:   python3 check_icloud.py -i ~/Pictures/Photos --report
  2. Download: python3 check_icloud.py -i ~/Pictures/Photos --download
  3. Scan:    python3 scan_photos.py -i ~/Pictures/Photos -o index.db
""")
    parser.add_argument("--source", "--input", "-i", dest="source", required=True,
                        help="Directory to scan for iCloud files")
    parser.add_argument("--report", action="store_true",
                        help="Print a report of iCloud-only files (default if no action specified)")
    parser.add_argument("--download", action="store_true",
                        help="Download all iCloud placeholder files")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --download: show what would be downloaded without actually downloading")
    args = parser.parse_args()

    source_dir = os.path.abspath(args.source)
    if not os.path.isdir(source_dir):
        print(f"Error: {source_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"\n  🔍 Scanning for iCloud placeholder files...")
    print(f"     Directory: {source_dir}\n")

    icloud_files = scan_directory_for_icloud(source_dir)

    if args.download:
        download_all(icloud_files, source_dir, dry_run=args.dry_run)
    else:
        print_report(icloud_files, source_dir)

    # Always show the report after download
    if args.download and not args.dry_run:
        print("  Final report:")
        print_report(icloud_files if not args.download else
                     scan_directory_for_icloud(source_dir), source_dir)


if __name__ == "__main__":
    main()
