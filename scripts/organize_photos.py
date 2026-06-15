#!/usr/bin/env python3
"""Interactive photo organizer — ask user preferences, then execute pipeline.

This script provides an interactive workflow for organizing photos:

1. **Ask preferences** — What kind of organizing? Which folders to prioritize?
2. **Scan** — Index the photo library (file-system or Photos.app)
3. **Detect** — Find duplicates using selected methods
4. **Preview** — Show summary and ask for confirmation (Fast/Safe path)
5. **Generate plan** — Create move plan with user's strategy
6. **Apply** — Execute with undo support

Instead of running 5 separate scripts manually, this one orchestrates
the full pipeline with user-friendly prompts and confirmation points.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

# Pipeline scripts
from scan_photos import scan_directory
from scan_photos_library import scan_photos_library
from find_exact_duplicates import find_duplicates_db
from find_similar_photos import (
    group_by_phash_db, detect_scaled_duplicates_db,
    detect_cross_format_duplicates_db, detect_bursts_db,
    write_csv as write_similar_csv,
)
from generate_move_plan import generate_plan, read_duplicates, load_metadata_db


# ---------------------------------------------------------------------------
# User preference collection
# ---------------------------------------------------------------------------

ORGANIZE_MODES = {
    "dedup": "Find and remove duplicate photos",
    "by-date": "Organize photos into date-based folders (YYYY/MM)",
    "by-location": "Organize photos by GPS location",
    "by-category": "Organize by category (screenshots, WeChat, bursts, etc.)",
}

DEDUP_METHODS = {
    "exact": "SHA-256 exact duplicates (byte-identical files)",
    "phash": "pHash perceptual duplicates (edits, crops, near-duplicates)",
    "scaled": "Scaled duplicates (same photo at different resolutions)",
    "cross-format": "Cross-format duplicates (HEIC + JPEG of same photo)",
    "burst": "Burst photos (sub-second grouping via SubSecTime)",
    "all": "All detection methods (recommended)",
}

STRATEGIES = {
    "quality": "Keep highest quality (resolution + file size + EXIF)",
    "oldest": "Keep oldest file (likely original)",
    "newest": "Keep newest file (latest edit)",
    "folder": "Keep files from preferred folder",
}

TRASH_MODES = {
    "move": "Move to review folder (safest, files stay on disk)",
    "trash": "Move to macOS Trash (recoverable via Finder)",
    "photos-trash": "Remove from Photos.app via PyObjC (keeps library consistent)",
}

# Confirmation thresholds
FAST_PATH_LIMIT = 9  # Fast path: 1-9 moves, brief confirmation
SAFE_PATH_LIMIT = 10  # Safe path: 10+ moves, require explicit yes


def collect_preferences_interactive():
    """Collect user preferences via interactive prompts (for non-AI usage)."""
    prefs = {}

    print("=" * 60)
    print("  SnapTidy — Interactive Photo Organizer")
    print("=" * 60)
    print()

    # 1. Source
    print("📁 Where are your photos?")
    print("  1. A folder on disk (e.g., ~/Pictures/Export)")
    print("  2. Photos.app library (reads Photos.sqlite)")
    source = input("  Choose (1/2): ").strip()
    if source == "2":
        prefs["source_type"] = "photos_library"
        default_lib = os.path.expanduser("~/Pictures/Photos Library.photoslibrary")
        lib = input(f"  Library path [{default_lib}]: ").strip()
        prefs["source_path"] = lib or default_lib
    else:
        prefs["source_type"] = "folder"
        folder = input("  Folder path: ").strip()
        prefs["source_path"] = os.path.expanduser(folder)

    # 2. Organize mode
    print()
    print("🎯 What kind of organizing?")
    for key, desc in ORGANIZE_MODES.items():
        print(f"  {key}: {desc}")
    mode = input("  Choose mode [dedup]: ").strip().lower()
    prefs["mode"] = mode if mode in ORGANIZE_MODES else "dedup"

    # 3. Dedup methods (if dedup mode)
    if prefs["mode"] == "dedup":
        print()
        print("🔍 Which duplicate detection methods?")
        for key, desc in DEDUP_METHODS.items():
            print(f"  {key}: {desc}")
        method = input("  Choose method [all]: ").strip().lower()
        prefs["dedup_method"] = method if method in DEDUP_METHODS else "all"

        # pHash threshold
        if prefs["dedup_method"] in ("phash", "all"):
            threshold = input("  pHash Hamming distance threshold [0]: ").strip()
            prefs["phash_threshold"] = int(threshold) if threshold.isdigit() else 0

    # 4. Strategy
    print()
    print("📊 Priority strategy for keeping duplicates:")
    for key, desc in STRATEGIES.items():
        print(f"  {key}: {desc}")
    strategy = input("  Choose strategy [quality]: ").strip().lower()
    prefs["strategy"] = strategy if strategy in STRATEGIES else "quality"

    # 5. Preferred folder
    print()
    print("📂 Prefer to keep photos from which folder? (e.g., DCIM, 相册)")
    print("  Leave empty for no preference")
    pref_folder = input("  Preferred folder: ").strip()
    prefs["prefer_folders"] = [f.strip() for f in pref_folder.split(",") if f.strip()] if pref_folder else []

    # 6. Trash mode
    print()
    print("🗑️  What to do with duplicates?")
    for key, desc in TRASH_MODES.items():
        print(f"  {key}: {desc}")
    trash = input("  Choose action [move]: ").strip().lower()
    prefs["trash_mode"] = trash if trash in TRASH_MODES else "move"

    return prefs


def collect_preferences_from_args(args):
    """Collect user preferences from command-line arguments."""
    prefs = {
        "source_type": args.source_type,
        "source_path": os.path.expanduser(args.source),
        "mode": args.mode,
        "dedup_method": args.dedup_method,
        "phash_threshold": args.threshold,
        "strategy": args.strategy,
        "prefer_folders": args.prefer_folder or [],
        "trash_mode": args.trash_mode,
    }
    return prefs


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

def run_scan(prefs: dict, output_db: str) -> bool:
    """Step 1: Scan the photo library."""
    source_path = prefs["source_path"]
    if prefs["source_type"] == "photos_library":
        scan_photos_library(source_path, output_db)
    else:
        scan_directory(source_path, output_db, use_db=True)
    return True


def run_detect(prefs: dict, index_db: str, output_csv: str) -> bool:
    """Step 2: Detect duplicates."""
    method = prefs.get("dedup_method", "all")
    threshold = prefs.get("phash_threshold", 0)

    all_results = []

    # Exact duplicates (always run)
    exact_results = find_duplicates_db(index_db)
    if exact_results:
        # Normalize exact results to match similar results format
        for r in exact_results:
            r["match_type"] = "exact_sha256"
            r["phash"] = r.pop("sha256", "")  # reuse phash field for hash value
            # Remove extra fields not in write_similar_csv schema
            for extra_key in list(r.keys()):
                if extra_key not in ("group_id", "file_path", "phash", "match_type"):
                    del r[extra_key]
        all_results.extend(exact_results)
        num_groups = len(set(r["group_id"] for r in exact_results))
        print(f"  Exact duplicates: {len(exact_results)} files in {num_groups} groups")

    # Similar duplicates
    if method in ("phash", "all"):
        phash_results = group_by_phash_db(index_db, threshold=threshold)
        all_results.extend(phash_results)
        if phash_results:
            num_groups = len(set(r["group_id"] for r in phash_results))
            print(f"  pHash: {len(phash_results)} files in {num_groups} groups")

    if method in ("scaled", "all"):
        scaled_results = detect_scaled_duplicates_db(index_db)
        all_results.extend(scaled_results)
        if scaled_results:
            num_groups = len(set(r["group_id"] for r in scaled_results))
            print(f"  Scaled: {len(scaled_results)} files in {num_groups} groups")

    if method in ("cross-format", "all"):
        cross_results = detect_cross_format_duplicates_db(index_db)
        all_results.extend(cross_results)
        if cross_results:
            num_groups = len(set(r["group_id"] for r in cross_results))
            print(f"  Cross-format: {len(cross_results)} files in {num_groups} groups")

    if method in ("burst", "all"):
        burst_results = detect_bursts_db(index_db)
        all_results.extend(burst_results)
        if burst_results:
            num_groups = len(set(r["group_id"] for r in burst_results))
            print(f"  Burst: {len(burst_results)} files in {num_groups} groups")

    # Renumber group IDs to avoid collisions between methods
    current_gid = 0
    old_to_new = {}
    for r in sorted(all_results, key=lambda x: (x.get("match_type", ""), x.get("group_id", 0))):
        old_key = (r.get("match_type", ""), r.get("group_id", 0))
        if old_key not in old_to_new:
            current_gid += 1
            old_to_new[old_key] = current_gid
        r["group_id"] = old_to_new[old_key]

    # Write combined results
    write_similar_csv(all_results, output_csv)
    total_groups = len(set(e["group_id"] for e in all_results)) if all_results else 0
    print(f"  Total: {len(all_results)} images in {total_groups} groups")
    return len(all_results) > 0


def run_plan(prefs: dict, duplicates_csv: str, index_db: str, plan_csv: str, target_root: str) -> int:
    """Step 3: Generate move plan. Returns number of planned moves."""
    groups, match_types = read_duplicates(duplicates_csv)
    metadata = load_metadata_db(index_db)

    plan = generate_plan(
        groups, match_types, metadata, target_root,
        strategy=prefs["strategy"],
        prefer_folders=prefs.get("prefer_folders", []),
        use_trash=(prefs["trash_mode"] in ("trash", "photos-trash")),
    )

    # Write plan
    import csv
    with open(plan_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["action", "source_path", "target_path", "reason"])
        writer.writeheader()
        for entry in plan:
            writer.writerow(entry)

    return len(plan)


def show_preview(index_db: str, plan_csv: str) -> dict:
    """Step 4: Show preview summary. Returns stats dict."""
    import csv

    stats = {"total_moves": 0, "by_category": {}, "by_match_type": {}, "reclaimable_bytes": 0}

    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row

    with open(plan_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stats["total_moves"] += 1
            # Category
            src = row.get("source_path", "")
            cursor = conn.execute("SELECT category, size_bytes FROM photos WHERE file_path = ?", (src,))
            r = cursor.fetchone()
            if r:
                cat = r["category"]
                stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
                try:
                    stats["reclaimable_bytes"] += int(r["size_bytes"] or 0)
                except (ValueError, TypeError):
                    pass
            # Match type
            reason = row.get("reason", "")
            for mt in ("identical pHash", "scaled duplicate", "cross-format duplicate", "burst photo", "fuzzy pHash"):
                if mt in reason:
                    stats["by_match_type"][mt] = stats["by_match_type"].get(mt, 0) + 1
                    break

    conn.close()
    return stats


def format_bytes(n: int) -> str:
    """Format bytes to human-readable string."""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.1f} GB"
    elif n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    elif n >= 1_024:
        return f"{n / 1_024:.1f} KB"
    return f"{n} bytes"


def generate_manifest(prefs: dict, plan_csv: str, stats: dict, manifest_path: str) -> None:
    """Generate a plan manifest JSON for user review."""
    import csv

    moves = []
    with open(plan_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            moves.append(row)

    manifest = {
        "version": "3.0",
        "generated_at": datetime.now().isoformat(),
        "preferences": prefs,
        "summary": {
            "total_moves": stats["total_moves"],
            "by_category": stats["by_category"],
            "by_match_type": stats["by_match_type"],
            "reclaimable_space": format_bytes(stats["reclaimable_bytes"]),
        },
        "moves": moves,
        "status": "pending_user_confirmation",
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def confirm_plan(stats: dict, prefs: dict) -> bool:
    """Ask user to confirm the plan. Uses Fast/Safe path model."""
    total = stats["total_moves"]
    reclaimable = format_bytes(stats["reclaimable_bytes"])

    print()
    print("=" * 60)
    print("  📋 Move Plan Preview")
    print("=" * 60)
    print(f"  Total moves: {total}")
    print(f"  Reclaimable space: {reclaimable}")

    if stats["by_category"]:
        print(f"  By category:")
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"    {cat}: {count}")

    if stats["by_match_type"]:
        print(f"  By match type:")
        for mt, count in sorted(stats["by_match_type"].items(), key=lambda x: -x[1]):
            print(f"    {mt}: {count}")

    print(f"  Action: {TRASH_MODES.get(prefs['trash_mode'], prefs['trash_mode'])}")
    print()

    # Fast path vs Safe path
    if total <= FAST_PATH_LIMIT:
        # Fast path: brief confirmation
        answer = input(f"  Move {total} files? [Y/n] ").strip().lower()
        return answer in ("", "y", "yes")
    else:
        # Safe path: require explicit yes
        print(f"  ⚠️  This will move {total} files. This is a large operation.")
        print(f"  A manifest has been saved for your review.")
        answer = input(f"  Type 'yes' to confirm, or 'no' to cancel: ").strip().lower()
        return answer == "yes"


# ---------------------------------------------------------------------------
# iCloud / External source helpers
# ---------------------------------------------------------------------------

def check_icloud_status(path: str) -> str:
    """Check if a file is an iCloud placeholder (not fully downloaded).

    Returns: "local", "icloud_placeholder", or "unknown"
    """
    # iCloud files that aren't downloaded have an extended attribute
    # or are zero-byte with a .icloud companion file
    try:
        if not os.path.exists(path):
            return "unknown"

        # Check for .icloud companion file (iCloud Drive style)
        dir_path = os.path.dirname(path)
        basename = os.path.basename(path)
        icloud_file = os.path.join(dir_path, f".{basename}.icloud")
        if os.path.exists(icloud_file):
            return "icloud_placeholder"

        # Check file size — iCloud placeholders are typically 0 bytes
        if os.path.getsize(path) == 0:
            # Could be iCloud placeholder or truly empty file
            # Check if the file has the iCloud extended attribute
            import subprocess
            result = subprocess.run(
                ["xattr", "-p", "com.apple.iCloud.syncState", path],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return "icloud_placeholder"

        return "local"
    except Exception:
        return "unknown"


def download_icloud_file(path: str) -> bool:
    """Trigger download of an iCloud file by reading it.

    Uses `brctl download` on macOS to trigger iCloud download.
    Returns True if download was triggered, False otherwise.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["brctl", "download", path],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        # Fallback: try opening the file to trigger download
        try:
            with open(path, "rb") as f:
                f.read(1)
            return True
        except Exception:
            return False


def detect_android_mount() -> list:
    """Detect mounted Android devices via Android File Transfer.

    Returns list of mount paths (e.g., ['/Volumes/Android']).
    """
    android_paths = []
    # Check common mount points
    for name in ("Android", "Galaxy", "Pixel", "OnePlus", "Xiaomi", "Huawei", "Samsung"):
        path = f"/Volumes/{name}"
        if os.path.ismount(path) or os.path.isdir(path):
            # Verify it looks like an Android device
            dcim = os.path.join(path, "DCIM")
            if os.path.isdir(dcim):
                android_paths.append(path)

    # Also check for MTP-style mounts
    for entry in os.listdir("/Volumes/"):
        full = os.path.join("/Volumes/", entry)
        if os.path.isdir(full):
            dcim = os.path.join(full, "DCIM")
            if os.path.isdir(dcim) and entry not in ("Macintosh HD", "VMware Shared Folders"):
                if full not in android_paths:
                    android_paths.append(full)

    return android_paths


def detect_external_drives() -> list:
    """Detect mounted external drives with photo content.

    Returns list of dicts: [{path, name, has_dcim, has_photos}]
    """
    drives = []
    for entry in os.listdir("/Volumes/"):
        full = os.path.join("/Volumes/", entry)
        if not os.path.isdir(full):
            continue
        if entry in ("Macintosh HD", "VMware Shared Folders", "Recovery", "com.apple.TimeMachine.localsnapshots"):
            continue

        has_dcim = os.path.isdir(os.path.join(full, "DCIM"))
        has_photos = os.path.isdir(os.path.join(full, "Photos")) or os.path.isdir(os.path.join(full, "photos"))
        has_pictures = os.path.isdir(os.path.join(full, "Pictures")) or os.path.isdir(os.path.join(full, "pictures"))

        if has_dcim or has_photos or has_pictures:
            drives.append({
                "path": full,
                "name": entry,
                "has_dcim": has_dcim,
                "has_photos": has_photos or has_pictures,
            })

    return drives


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SnapTidy interactive photo organizer — ask preferences, run pipeline")
    parser.add_argument("--source", "-i", required=True,
                        help="Path to photo folder or .photoslibrary bundle")
    parser.add_argument("--source-type", choices=["folder", "photos_library"], default="folder",
                        help="Source type: folder or Photos.app library (auto-detected from path)")
    parser.add_argument("--mode", choices=list(ORGANIZE_MODES.keys()), default="dedup",
                        help="Organize mode (default: dedup)")
    parser.add_argument("--dedup-method", choices=list(DEDUP_METHODS.keys()), default="all",
                        help="Duplicate detection method (default: all)")
    parser.add_argument("--threshold", type=int, default=0,
                        help="pHash Hamming distance threshold (default: 0)")
    parser.add_argument("--strategy", choices=list(STRATEGIES.keys()), default="quality",
                        help="Priority strategy (default: quality)")
    parser.add_argument("--prefer-folder", action="append", default=[],
                        help="Preferred folder tag (can specify multiple)")
    parser.add_argument("--trash-mode", choices=list(TRASH_MODES.keys()), default="move",
                        help="Action for duplicates (default: move)")
    parser.add_argument("--output-dir", default="./snaptidy_output",
                        help="Output directory for index, duplicates, plan (default: ./snaptidy_output)")
    parser.add_argument("--interactive", action="store_true",
                        help="Run in interactive mode with prompts")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — don't apply moves")
    parser.add_argument("--check-icloud", action="store_true",
                        help="Check iCloud download status before scanning")
    parser.add_argument("--detect-sources", action="store_true",
                        help="Detect external drives and Android devices")
    args = parser.parse_args()

    # Auto-detect source type
    source_type = args.source_type
    if args.source.endswith(".photoslibrary"):
        source_type = "photos_library"

    # Detect external sources if requested
    if args.detect_sources:
        print("🔍 Detecting external sources...")
        android = detect_android_mount()
        if android:
            print("  Android devices found:")
            for p in android:
                print(f"    📱 {p} (DCIM folder detected)")
        ext_drives = detect_external_drives()
        if ext_drives:
            print("  External drives with photos:")
            for d in ext_drives:
                flags = []
                if d["has_dcim"]:
                    flags.append("DCIM")
                if d["has_photos"]:
                    flags.append("Photos")
                print(f"    💾 {d['name']} ({', '.join(flags)})")
        if not android and not ext_drives:
            print("  No external sources found.")
            print("  Tip: Connect an Android phone or external drive and try again.")
        print()

    # Collect preferences
    if args.interactive:
        prefs = collect_preferences_interactive()
    else:
        prefs = collect_preferences_from_args(args)
        prefs["source_type"] = source_type

    # Setup output directory
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    index_db = os.path.join(output_dir, "photo_index.db")
    duplicates_csv = os.path.join(output_dir, "duplicates.csv")
    plan_csv = os.path.join(output_dir, "move_plan.csv")
    manifest_path = os.path.join(output_dir, "plan_manifest.json")

    # Step 1: Scan
    print()
    print("📷 Step 1/5: Scanning photo library...")
    run_scan(prefs, index_db)

    # Check iCloud status
    if args.check_icloud or prefs["source_type"] == "photos_library":
        conn = sqlite3.connect(index_db)
        conn.row_factory = sqlite3.Row
        # Count iCloud-only files
        cursor = conn.execute("""
            SELECT COUNT(*) FROM photos WHERE photos_cloud_state > 0
        """)
        icloud_count = cursor.fetchone()[0]
        if icloud_count > 0:
            print(f"  ☁️  {icloud_count} files may be iCloud-only (not fully downloaded)")
            print(f"     These files will be skipped during move operations.")
        conn.close()

    # Step 2: Detect
    print()
    print("🔍 Step 2/5: Detecting duplicates...")
    has_duplicates = run_detect(prefs, index_db, duplicates_csv)

    if not has_duplicates:
        print()
        print("✅ No duplicates found! Your library is clean.")
        return

    # Step 3: Generate plan
    print()
    print("📝 Step 3/5: Generating move plan...")
    num_moves = run_plan(prefs, duplicates_csv, index_db, plan_csv, prefs["source_path"])
    print(f"  Generated {num_moves} planned moves")

    # Step 4: Preview & confirm
    print()
    print("👀 Step 4/5: Preview...")
    stats = show_preview(index_db, plan_csv)
    generate_manifest(prefs, plan_csv, stats, manifest_path)
    print(f"  Manifest saved to: {manifest_path}")

    if args.dry_run:
        print()
        print("🏁 Dry run complete — no files were moved.")
        print(f"   Review the manifest: {manifest_path}")
        return

    # Confirmation
    if not confirm_plan(stats, prefs):
        print("  ❌ Cancelled. No files were moved.")
        print(f"   The plan is saved at: {plan_csv}")
        return

    # Step 5: Apply
    print()
    print("🚀 Step 5/5: Applying move plan...")
    from apply_move_plan import apply_plan
    log_path = os.path.join(output_dir, "move_log.csv")
    apply_plan(plan_csv, log_path, mode=prefs["trash_mode"])
    print()
    print("✅ Done! Check move_log.csv for details.")


if __name__ == "__main__":
    main()
