#!/usr/bin/env python3
"""Check and pre-download iCloud-only files before scanning.

When macOS "Optimize Storage" is enabled, iCloud offloads original photos
to the cloud and keeps only small thumbnails locally (2-50 KB).  These
thumbnails produce unreliable SHA-256 hashes and pHashes, causing false
negatives in duplicate detection and incorrect metadata.

This script scans a directory for iCloud placeholder files and can:
  1. Report how many files are iCloud-only and their total size
  2. Estimate the download size needed (originals are typically 10-50x larger)
  3. Check available disk space before attempting download
  4. Batch download all iCloud files with progress reporting
  5. Download in batches when disk space is limited (--max-download)
  6. Verify that all files are now local before running downstream tools

Typical workflow:
    # Step 1: Check what needs downloading
    python3 check_icloud.py --source ~/Pictures/PhotoLibrary --report

    # Step 2: Download all iCloud files
    python3 check_icloud.py --source ~/Pictures/PhotoLibrary --download

    # Step 2b: Download in batches (when disk space is limited)
    python3 check_icloud.py --source ~/Pictures/PhotoLibrary --download --max-download 100

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
    estimate_download_size,
    get_disk_space,
    is_likely_thumbnail,
    scan_directory_for_icloud,
    THUMBNAIL_THRESHOLD_HEIC,
    THUMBNAIL_THRESHOLD_JPEG,
    DEFAULT_MIN_FREE_SPACE,
    ESTIMATED_SIZE_MULTIPLIER,
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
    estimated_original_size = estimate_download_size(icloud_files)

    # Check disk space
    _, _, free_space = get_disk_space(source_dir)

    print("\n" + "=" * 64)
    print("  ☁️  iCloud Placeholder Report")
    print("=" * 64)
    print(f"\n  📁 Source directory: {source_dir}")
    print(f"  📄 iCloud-only files: {total}")
    print(f"  💾 Current local size (thumbnails): {format_size(total_thumbnail_size)}")
    print(f"  📥 Estimated download size needed: {format_size(estimated_original_size)}")
    print(f"     (estimates originals are ~{ESTIMATED_SIZE_MULTIPLIER}x larger than thumbnails)")
    print(f"  💽 Available disk space: {format_size(free_space)}")

    # Disk space warning
    min_free = DEFAULT_MIN_FREE_SPACE
    available_for_download = max(0, free_space - min_free)
    if estimated_original_size > available_for_download:
        shortfall = estimated_original_size - available_for_download
        print(f"\n  ⚠️  DISK SPACE WARNING")
        print(f"     Estimated download ({format_size(estimated_original_size)}) exceeds")
        print(f"     available space ({format_size(available_for_download)} after {format_size(min_free)} buffer)")
        print(f"     Shortfall: {format_size(shortfall)}")

        # Calculate how many files can be downloaded
        if total > 0:
            avg_per_file = estimated_original_size / total
            max_files = int(available_for_download / avg_per_file) if avg_per_file > 0 else 0
            print(f"\n  💡 You can download ~{max_files} of {total} files with current free space.")
            print(f"     Use --max-download {max_files} to download in batches:")
            print(f"     python3 check_icloud.py -i \"{source_dir}\" --download --max-download {max_files}")
            print(f"\n  Or use --skip-icloud to scan without downloading:")
            print(f"     python3 scan_photos.py -i \"{source_dir}\" -o index.db --skip-icloud")
            print(f"\n  Or free up disk space and try again.")
    else:
        print(f"     ✅ Sufficient space for download (after {format_size(min_free)} buffer)")

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


def download_all(icloud_files: list, source_dir: str, dry_run: bool = False,
                 max_download: int = 0, min_free_gb: float = 5.0,
                 batch_size: int = 0) -> None:
    """Download iCloud placeholder files with progress reporting.

    Args:
        icloud_files: list of iCloud file info dicts
        source_dir: source directory (for disk space check)
        dry_run: if True, only show what would be downloaded
        max_download: if > 0, download at most this many files
        min_free_gb: minimum free disk space to keep (GB), safety buffer
        batch_size: if > 0, download in batches of this size, checking disk
                    space between batches
    """
    total = len(icloud_files)
    if total == 0:
        print("\n  ✅ No iCloud placeholder files to download.")
        return

    # Apply max_download limit
    files_to_download = icloud_files
    if max_download > 0 and max_download < total:
        files_to_download = icloud_files[:max_download]
        print(f"\n  📋 Limiting to {max_download} of {total} files (--max-download)")
        total = max_download

    # Disk space check
    estimated_size = estimate_download_size(files_to_download)
    _, _, free_space = get_disk_space(source_dir)
    min_free_bytes = int(min_free_gb * 1024 * 1024 * 1024)
    available_for_download = max(0, free_space - min_free_bytes)

    print(f"\n  📥 Preparing to download {total} iCloud files...")
    print(f"     Estimated download size: {format_size(estimated_size)}")
    print(f"     Available disk space: {format_size(free_space)}")
    print(f"     Safety buffer: {format_size(min_free_bytes)} ({min_free_gb:.0f} GB)")
    print(f"     Available for download: {format_size(available_for_download)}")

    if estimated_size > available_for_download:
        shortfall = estimated_size - available_for_download
        print(f"\n  ❌ INSUFFICIENT DISK SPACE")
        print(f"     Need {format_size(estimated_size)} but only {format_size(available_for_download)} available")
        print(f"     Shortfall: {format_size(shortfall)}")

        if total > 0:
            avg_per_file = estimated_size / total
            max_files = int(available_for_download / avg_per_file) if avg_per_file > 0 else 0
            print(f"\n  💡 Options:")
            print(f"     1. Download in smaller batches:")
            print(f"        python3 check_icloud.py -i \"{source_dir}\" --download --max-download {max_files}")
            print(f"     2. Skip iCloud files during scan (metadata may be unreliable):")
            print(f"        python3 scan_photos.py -i \"{source_dir}\" -o index.db --skip-icloud")
            print(f"     3. Free up disk space (need {format_size(shortfall)} more)")
            print(f"     4. Reduce safety buffer (not recommended, min-free < {min_free_gb:.0f} GB):")
            print(f"        python3 check_icloud.py -i \"{source_dir}\" --download --min-free 2")
            print(f"\n  Use --force to download anyway (may fail mid-way).")
        return

    print(f"     ✅ Sufficient space for download\n")

    if dry_run:
        print("  [DRY RUN] Would download the following files:")
        for f in files_to_download[:20]:
            print(f"     {f['path']}")
        if total > 20:
            print(f"     ... and {total - 20} more")
        return

    downloaded = 0
    failed = 0
    skipped = 0
    start_time = time.monotonic()
    last_pct = -1
    batch_downloaded = 0
    batch_failed = 0

    for idx, f in enumerate(files_to_download):
        path = f["path"]

        # Periodic disk space check (every 10 files or at batch boundary)
        if batch_size > 0 and idx > 0 and idx % batch_size == 0:
            _, _, current_free = get_disk_space(source_dir)
            if current_free < min_free_bytes:
                print(f"\n  ⛔ Stopping: disk space below safety buffer ({format_size(current_free)} < {format_size(min_free_bytes)})")
                print(f"     Downloaded {downloaded}/{total} files so far.")
                print(f"     Run again after freeing space, or use --max-download to continue from here.")
                break
            print(f"  📦 Batch checkpoint: {downloaded} downloaded, {format_size(current_free)} free\n")

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
            _, _, current_free = get_disk_space(source_dir)
            print(f"  [{idx + 1}/{total}] ({pct}%) "
                  f"~{remaining:.0f}s remaining — {os.path.basename(path)} "
                  f"[{format_size(current_free)} free]")
            last_pct = pct

        # Download
        success = download_icloud_file(path)
        if success:
            downloaded += 1
        else:
            failed += 1
            print(f"     ❌ Failed: {path}")

        # Check disk space after each download
        _, _, current_free = get_disk_space(source_dir)
        if current_free < min_free_bytes:
            print(f"\n  ⛔ Stopping: disk space below safety buffer after download")
            print(f"     {format_size(current_free)} free (need {format_size(min_free_bytes)} buffer)")
            print(f"     Downloaded {downloaded}/{total} files so far.")
            remaining_files = total - idx - 1
            if remaining_files > 0:
                print(f"     {remaining_files} files not downloaded. Free up space and run again,")
                print(f"     or use --skip-icloud to scan without them.")
            break

    elapsed = time.monotonic() - start_time
    print(f"\n  {'=' * 48}")
    print(f"  Download complete in {elapsed:.0f}s")
    print(f"  ✅ Downloaded: {downloaded}")
    print(f"  ⏭️  Skipped (already local): {skipped}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📄 Not attempted: {total - downloaded - failed - skipped}")

    if failed > 0:
        print(f"\n  ⚠️  {failed} files could not be downloaded.")
        print(f"     They may not be available in iCloud, or iCloud sync is disabled.")
        print(f"     You can still scan with --skip-icloud to exclude them.")

    # Final verification
    remaining = scan_directory_for_icloud(source_dir)
    if remaining:
        print(f"\n  ⚠️  {len(remaining)} iCloud placeholder files still remain.")
        print(f"     Run check_icloud.py again, or use scan_photos.py --skip-icloud")
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

When disk space is limited:
  # Download in batches of 100
  python3 check_icloud.py -i ~/Pictures/Photos --download --max-download 100

  # Or scan without downloading (metadata may be unreliable)
  python3 scan_photos.py -i ~/Pictures/Photos -o index.db --skip-icloud
""")
    parser.add_argument("--source", "--input", "-i", dest="source", required=True,
                        help="Directory to scan for iCloud files")
    parser.add_argument("--report", action="store_true",
                        help="Print a report of iCloud-only files (default if no action specified)")
    parser.add_argument("--download", action="store_true",
                        help="Download all iCloud placeholder files")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --download: show what would be downloaded without actually downloading")
    parser.add_argument("--max-download", type=int, default=0,
                        help="Maximum number of files to download (0 = all)")
    parser.add_argument("--min-free", type=float, default=5.0,
                        help="Minimum free disk space in GB to keep as safety buffer (default: 5)")
    parser.add_argument("--batch-size", type=int, default=0,
                        help="Check disk space every N files during download (0 = check after each file)")
    parser.add_argument("--force", action="store_true",
                        help="Download even if disk space check fails (not recommended)")
    args = parser.parse_args()

    source_dir = os.path.abspath(args.source)
    if not os.path.isdir(source_dir):
        print(f"Error: {source_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"\n  🔍 Scanning for iCloud placeholder files...")
    print(f"     Directory: {source_dir}\n")

    icloud_files = scan_directory_for_icloud(source_dir)

    if args.download:
        if args.force and not args.dry_run:
            # Skip disk space check, just download
            print("  ⚠️  --force: skipping disk space check (may fail mid-way)\n")
            download_all(icloud_files, source_dir, dry_run=args.dry_run,
                        max_download=args.max_download, min_free_gb=0,
                        batch_size=args.batch_size)
        else:
            download_all(icloud_files, source_dir, dry_run=args.dry_run,
                        max_download=args.max_download, min_free_gb=args.min_free,
                        batch_size=args.batch_size)
    else:
        print_report(icloud_files, source_dir)

    # Always show the report after download
    if args.download and not args.dry_run:
        print("  Final report:")
        print_report(scan_directory_for_icloud(source_dir), source_dir)


if __name__ == "__main__":
    main()
