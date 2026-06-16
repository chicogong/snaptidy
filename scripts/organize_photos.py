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
import subprocess
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
    "photos-album": "Organize photos into albums in Photos.app (by date/category/format)",
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
    "oldest": "Keep oldest file (likely the original)",
    "newest": "Keep newest file (latest edit)",
    "folder": "Keep files from preferred folder/album",
}

TRASH_MODES = {
    "move": "Move to review folder (safest, files stay on disk)",
    "trash": "Move to macOS Trash (recoverable via Finder)",
    "photos-trash": "Remove from Photos.app via AppleScript (30-day recovery in Recently Deleted)",
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

    # 5.5. Album preferences (for Photos Library sources)
    prefs["prefer_albums"] = []
    if prefs["source_type"] == "photos_library":
        print()
        print("📁 Prefer to keep photos from which album? (e.g., \"My Favorites\", \"旅行\")")
        print("  Leave empty for no preference")
        pref_album = input("  Preferred album: ").strip()
        prefs["prefer_albums"] = [a.strip() for a in pref_album.split(",") if a.strip()] if pref_album else []

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
    exact_results, _ = find_duplicates_db(index_db)
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


def generate_by_date_plan(index_db: str, plan_csv: str, target_root: str, date_format: str = "YYYY/MM") -> int:
    """Generate a move plan that organizes photos into date-based folders.

    Uses EXIF DateTimeOriginal first, falls back to file mtime.

    date_format options:
      - "YYYY/MM" — e.g., 2024/06 (default)
      - "YYYY-MM" — e.g., 2024-06
      - "YYYY"    — e.g., 2024
      - "YYYY/MM/DD" — e.g., 2024/06/15

    Returns number of planned moves.
    """
    import csv
    from datetime import datetime as dt

    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row

    plan = []
    skipped = 0

    cursor = conn.execute("SELECT file_path, exif_datetime, file_mtime, category FROM photos")
    for row in cursor:
        src = row["file_path"]
        date_str = row["exif_datetime"] or row["file_mtime"] or ""

        if not date_str:
            skipped += 1
            continue

        # Parse date
        try:
            # Try ISO format first
            if "T" in date_str:
                parsed = dt.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                # Try common formats
                for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                    try:
                        parsed = dt.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    skipped += 1
                    continue
        except (ValueError, TypeError):
            skipped += 1
            continue

        # Build target folder path
        if date_format == "YYYY/MM":
            folder = f"{parsed.year:04d}/{parsed.month:02d}"
        elif date_format == "YYYY-MM":
            folder = f"{parsed.year:04d}-{parsed.month:02d}"
        elif date_format == "YYYY":
            folder = f"{parsed.year:04d}"
        elif date_format == "YYYY/MM/DD":
            folder = f"{parsed.year:04d}/{parsed.month:02d}/{parsed.day:02d}"
        else:
            folder = f"{parsed.year:04d}/{parsed.month:02d}"

        # Build target path
        filename = os.path.basename(src)
        target_path = os.path.join(target_root, folder, filename)

        # Skip if already in the correct folder
        src_dir = os.path.dirname(src)
        expected_dir = os.path.join(target_root, folder)
        if os.path.normpath(src_dir) == os.path.normpath(expected_dir):
            continue

        plan.append({
            "action": "move",
            "source_path": src,
            "target_path": target_path,
            "reason": f"organize by date: {folder}",
        })

    conn.close()

    # Write plan
    with open(plan_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["action", "source_path", "target_path", "reason"])
        writer.writeheader()
        for entry in plan:
            writer.writerow(entry)

    if skipped:
        print(f"  Skipped {skipped} files without valid date")

    return len(plan)


def generate_by_category_plan(index_db: str, plan_csv: str, target_root: str) -> int:
    """Generate a move plan that organizes photos into category-based folders.

    Folder structure: target_root/{category}/filename
    e.g., target_root/screenshots/screenshot_20240615.png

    Returns number of planned moves.
    """
    import csv

    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row

    plan = []
    skipped = 0

    # Category → folder name mapping
    CATEGORY_FOLDERS = {
        "photo": "01_Photos",
        "screenshot": "02_Screenshots",
        "wechat": "03_WeChat",
        "burst": "04_Burst",
        "video": "05_Videos",
    }

    cursor = conn.execute("SELECT file_path, category FROM photos")
    for row in cursor:
        src = row["file_path"]
        cat = row["category"] or "photo"

        folder = CATEGORY_FOLDERS.get(cat, f"06_Other_{cat}")
        filename = os.path.basename(src)
        target_path = os.path.join(target_root, folder, filename)

        # Skip if already in the correct folder
        src_dir = os.path.dirname(src)
        expected_dir = os.path.join(target_root, folder)
        if os.path.normpath(src_dir) == os.path.normpath(expected_dir):
            continue

        plan.append({
            "action": "move",
            "source_path": src,
            "target_path": target_path,
            "reason": f"organize by category: {cat}",
        })

    conn.close()

    # Write plan
    with open(plan_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["action", "source_path", "target_path", "reason"])
        writer.writeheader()
        for entry in plan:
            writer.writerow(entry)

    return len(plan)


# ---------------------------------------------------------------------------
# Photos.app album organization
# ---------------------------------------------------------------------------

ALBUM_ORGANIZE_MODES = {
    "date": "Create albums by year/month (e.g., '2026/01 – January')",
    "year": "Create albums by year (e.g., '2026')",
    "category": "Create albums by category (e.g., '📸 Photos', '📱 Screenshots')",
    "format": "Create albums by format (e.g., 'JPEG', 'HEIC', 'PNG')",
    "smart": "Create albums by year/category (e.g., '2026/📸 Photos', '2026/📱 Screenshots')",
}

# Category → album name mapping (with emoji prefix for visual distinction)
CATEGORY_ALBUM_NAMES = {
    "photo": "📸 Photos",
    "screenshot": "📱 Screenshots",
    "wechat": "💬 WeChat",
    "burst": "🔄 Burst",
    "video": "🎬 Videos",
}

# Format → album name mapping
FORMAT_ALBUM_NAMES = {
    "jpeg": "JPEG",
    "heic": "HEIC",
    "png": "PNG",
    "tiff": "TIFF",
    "raw": "RAW",
    "webp": "WebP",
    "other": "Other",
}


def _photos_album_exists(album_name: str) -> bool:
    """Check if an album already exists in Photos.app via AppleScript."""
    escaped_name = album_name.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "Photos"
    try
        set a to album "{escaped_name}"
        return "exists"
    on error
        return "not_found"
    end try
end tell
'''
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        return "exists" in result.stdout.strip()
    except Exception:
        return False


def _photos_create_album(album_name: str) -> bool:
    """Create a new album in Photos.app via AppleScript. Returns True if successful."""
    # Escape double quotes in album name
    escaped_name = album_name.replace("\\", "\\\\").replace('"', '\\"')
    # Use make new album + set name (the "named" parameter doesn't work in some locales)
    script = f'''
tell application "Photos"
    try
        set a to make new album
        set name of a to "{escaped_name}"
        return "created"
    on error errMsg
        return "error:" & errMsg
    end try
end tell
'''
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        return "created" in result.stdout.strip()
    except Exception:
        return False


def _photos_add_to_album(uuids: list, album_name: str) -> tuple:
    """Add photos (by UUID list) to an album in Photos.app via AppleScript.

    Returns (success_count, error_count).
    """
    if not uuids:
        return 0, 0

    escaped_name = album_name.replace("\\", "\\\\").replace('"', '\\"')

    # Process in batches of 10 to avoid AppleScript timeout
    batch_size = 10
    success = 0
    errors = 0

    for i in range(0, len(uuids), batch_size):
        batch = uuids[i:i + batch_size]

        # Build AppleScript to add items to album
        # NOTE: Photos.app requires `add {item} to album` (list syntax),
        # not `add item to album` (singular syntax fails with "doesn't understand add message")
        items_code = ""
        for uuid in batch:
            photos_id = f"{uuid}/L0/001"
            items_code += f'''
        try
            set theItem to media item id "{photos_id}"
            add {{theItem}} to targetAlbum
            set addedCount to addedCount + 1
        on error
            set errorCount to errorCount + 1
        end try
'''

        script = f'''
tell application "Photos"
    set targetAlbum to album "{escaped_name}"
    set addedCount to 0
    set errorCount to 0
{items_code}
    return (addedCount as text) & "," & (errorCount as text)
end tell
'''
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                capture_output=True, text=True, timeout=30,
            )
            output = result.stdout.strip()
            if "," in output:
                parts = output.split(",")
                try:
                    success += int(parts[0])
                    errors += int(parts[1])
                except ValueError:
                    errors += len(batch)
            else:
                errors += len(batch)
        except subprocess.TimeoutExpired:
            errors += len(batch)
        except Exception:
            errors += len(batch)

    return success, errors


def _photos_list_existing_albums() -> dict:
    """List all albums in Photos.app. Returns {album_name: photo_count}."""
    script = '''
tell application "Photos"
    set albumInfo to {}
    repeat with a in albums
        set aName to name of a
        set aCount to count of media items of a
        set end of albumInfo to aName & ":" & aCount
    end repeat
    set AppleScript's text item delimiters to "|"
    return albumInfo as text
end tell
'''
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
        albums = {}
        for item in result.stdout.strip().split("|"):
            item = item.strip()
            if ":" in item:
                name, count = item.rsplit(":", 1)
                try:
                    albums[name.strip()] = int(count.strip())
                except ValueError:
                    albums[name.strip()] = 0
        return albums
    except Exception:
        return {}


def organize_photos_albums(index_db: str, organize_by: str = "date",
                           dry_run: bool = False) -> dict:
    """Organize photos into albums in Photos.app.

    organize_by options:
      "date"     — Albums by year/month (e.g., "2026/01 – January")
      "year"     — Albums by year (e.g., "2026")
      "category" — Albums by category (e.g., "📸 Photos", "📱 Screenshots")
      "format"   — Albums by format (e.g., "JPEG", "HEIC")
      "smart"    — Albums by year/category (e.g., "2026/📸 Photos")

    Returns a dict with stats: {albums_created, photos_added, errors, details}
    """
    import re

    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row
    stats = {"albums_created": 0, "photos_added": 0, "errors": 0, "details": []}

    # Step 1: Group photos by the desired dimension
    # We need UUID (from filename) for AppleScript references
    groups = {}  # album_name -> [uuid, ...]

    cursor = conn.execute("SELECT file_path, filename, exif_datetime, file_mtime, category, format_family FROM photos")
    for row in cursor:
        filepath = row["file_path"]
        filename = row["filename"]
        exif_dt = row["exif_datetime"] or row["file_mtime"] or ""
        category = row["category"] or "photo"
        fmt_family = row["format_family"] or "other"

        # Extract UUID from filename (Photos.app stores UUID.ext)
        uuid_part = os.path.splitext(filename)[0]
        if len(uuid_part) < 32:
            continue  # Not a UUID-based filename, skip

        # Determine album name
        if organize_by == "date":
            if not exif_dt:
                album_name = "📅 No Date"
            else:
                # Parse date
                try:
                    if "T" in exif_dt:
                        from datetime import datetime as dt
                        parsed = dt.fromisoformat(exif_dt.replace("Z", "+00:00"))
                    else:
                        from datetime import datetime as dt
                        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                            try:
                                parsed = dt.strptime(exif_dt[:19], fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            album_name = "📅 No Date"
                            groups.setdefault(album_name, []).append(uuid_part)
                            continue
                    month_names = {
                        1: "January", 2: "February", 3: "March", 4: "April",
                        5: "May", 6: "June", 7: "July", 8: "August",
                        9: "September", 10: "October", 11: "November", 12: "December",
                    }
                    album_name = f"{parsed.year:04d}/{parsed.month:02d} – {month_names.get(parsed.month, '')}"
                except Exception:
                    album_name = "📅 No Date"

        elif organize_by == "year":
            if not exif_dt:
                album_name = "📅 No Date"
            else:
                try:
                    year = exif_dt[:4]
                    if year.isdigit() and int(year) > 1990:
                        album_name = year
                    else:
                        album_name = "📅 No Date"
                except Exception:
                    album_name = "📅 No Date"

        elif organize_by == "category":
            album_name = CATEGORY_ALBUM_NAMES.get(category, f"📁 {category.title()}")

        elif organize_by == "format":
            album_name = FORMAT_ALBUM_NAMES.get(fmt_family, fmt_family.title())

        elif organize_by == "smart":
            # year/category
            if exif_dt:
                try:
                    year = exif_dt[:4]
                    if not (year.isdigit() and int(year) > 1990):
                        year = "Unknown"
                except Exception:
                    year = "Unknown"
            else:
                year = "No Date"
            cat_name = CATEGORY_ALBUM_NAMES.get(category, category.title())
            album_name = f"{year}/{cat_name}"
        else:
            album_name = "Other"

        groups.setdefault(album_name, []).append(uuid_part)

    conn.close()

    if not groups:
        print("  ⚠️  No photos to organize into albums.")
        return stats

    # Step 2: Preview
    print()
    print("📋 Album Organization Plan:")
    print("─" * 60)
    for album_name, uuids in sorted(groups.items()):
        print(f"  📁 {album_name}: {len(uuids)} photos")
    print()

    if dry_run:
        print("🏁 Dry run — no albums were created.")
        print(f"   Would create {len(groups)} albums with {sum(len(v) for v in groups.values())} photos")
        stats["details"] = [{"album": name, "count": len(uuids)} for name, uuids in sorted(groups.items())]
        return stats

    # Step 3: Check permission
    from apply_move_plan import ensure_photos_permission
    if not ensure_photos_permission():
        print("  ❌ Cannot organize albums without Photos.app automation permission.")
        return stats

    # Step 4: Create albums and add photos
    existing_albums = _photos_list_existing_albums()

    for album_name, uuids in sorted(groups.items()):
        # Check if album already exists
        album_existed = album_name in existing_albums

        if not album_existed:
            print(f"  📁 Creating album: {album_name}...", end=" ", flush=True)
            if _photos_create_album(album_name):
                stats["albums_created"] += 1
                print("✅")
            else:
                print("❌ Failed to create")
                stats["errors"] += len(uuids)
                stats["details"].append({"album": album_name, "count": len(uuids), "status": "create_failed"})
                continue
        else:
            print(f"  📁 Album exists: {album_name} (adding {len(uuids)} photos)", end=" ", flush=True)

        # Add photos to album
        success, errors = _photos_add_to_album(uuids, album_name)
        stats["photos_added"] += success
        stats["errors"] += errors
        if errors == 0:
            print(f"✅ {success} added")
        else:
            print(f"⚠️  {success} added, {errors} failed")
        stats["details"].append({
            "album": album_name,
            "count": len(uuids),
            "added": success,
            "errors": errors,
            "existed": album_existed,
        })

    return stats


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
    try:
        for entry in os.listdir("/Volumes/"):
            full = os.path.join("/Volumes/", entry)
            if os.path.isdir(full):
                dcim = os.path.join(full, "DCIM")
                if os.path.isdir(dcim) and entry not in ("Macintosh HD", "VMware Shared Folders"):
                    if full not in android_paths:
                        android_paths.append(full)
    except PermissionError:
        pass

    return android_paths


def detect_external_drives() -> list:
    """Detect mounted external drives with photo content.

    Returns list of dicts: [{path, name, has_dcim, has_photos}]
    """
    drives = []
    try:
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
    except PermissionError:
        pass

    return drives


# ---------------------------------------------------------------------------
# Album helpers
# ---------------------------------------------------------------------------

def _list_albums(index_db: str) -> None:
    """List available albums and their photo counts from the scan index."""
    print()
    print("📋 Available Albums:")
    print("─" * 50)
    try:
        conn = sqlite3.connect(index_db)
        # Check if photos_albums column exists
        cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
        if "photos_albums" not in cols:
            print("  ⚠️  No album data in this scan. Use --source-type photos_library to scan albums.")
            conn.close()
            return

        # Parse album membership (comma-separated in photos_albums)
        album_counts = {}
        cursor = conn.execute("SELECT photos_albums FROM photos WHERE photos_albums != ''")
        for (albums_str,) in cursor:
            for album in albums_str.split(","):
                album = album.strip()
                if album:
                    album_counts[album] = album_counts.get(album, 0) + 1

        conn.close()

        if not album_counts:
            print("  No albums found.")
            return

        for album, count in sorted(album_counts.items(), key=lambda x: -x[1]):
            print(f"  📁 {album}: {count} photos")
        print()
        print("  Use --album-filter to process only specific albums")
        print("  Use --exclude-album to skip specific albums")
        print("  Use --prefer-album to prefer keeping photos from specific albums")
    except Exception as e:
        print(f"  Error reading albums: {e}")


def _apply_album_filter(index_db: str, album_filter: list, exclude_album: list) -> None:
    """Filter photos in the index DB by album membership.

    Removes photos that don't match --album-filter or that match --exclude-album.
    """
    conn = sqlite3.connect(index_db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    if "photos_albums" not in cols:
        print("  ⚠️  No album data — --album-filter and --exclude-album require Photos Library scan.")
        conn.close()
        return

    total_before = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    remove_paths = set()

    cursor = conn.execute("SELECT file_path, photos_albums FROM photos WHERE photos_albums != ''")
    for path, albums_str in cursor:
        albums = [a.strip() for a in albums_str.split(",") if a.strip()]

        # --album-filter: keep only photos in at least one specified album
        if album_filter:
            if not any(a in album_filter for a in albums):
                remove_paths.add(path)

        # --exclude-album: remove photos in any specified album
        if exclude_album:
            if any(a in exclude_album for a in albums):
                remove_paths.add(path)

    # Also remove photos with no album if album_filter is specified
    if album_filter:
        no_album = conn.execute(
            "SELECT file_path FROM photos WHERE photos_albums = '' OR photos_albums IS NULL"
        ).fetchall()
        for (path,) in no_album:
            remove_paths.add(path)

    if remove_paths:
        conn.executemany("DELETE FROM photos WHERE file_path = ?",
                         [(p,) for p in remove_paths])
        conn.commit()

    total_after = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    conn.close()

    removed = total_before - total_after
    if removed > 0:
        print(f"  📋 Album filter: removed {removed} photos, {total_after} remaining")
        if album_filter:
            print(f"     Included albums: {', '.join(album_filter)}")
        if exclude_album:
            print(f"     Excluded albums: {', '.join(exclude_album)}")
    else:
        print(f"  📋 Album filter: no photos filtered out ({total_after} remaining)")


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
    parser.add_argument("--album-filter", action="append", default=[],
                        help="Only process photos in specified album(s). "
                             "Can be used multiple times. Use --list-albums to see available albums.")
    parser.add_argument("--exclude-album", action="append", default=[],
                        help="Skip photos in specified album(s). Can be used multiple times.")
    parser.add_argument("--list-albums", action="store_true",
                        help="List available albums in the source and exit.")
    parser.add_argument("--prefer-album", action="append", default=[],
                        help="Prefer keeping photos from specified album(s) when choosing which duplicate to keep. "
                             "Used with --strategy folder.")
    parser.add_argument("--album-organize-by", choices=list(ALBUM_ORGANIZE_MODES.keys()), default="date",
                        help="Album organization dimension for --mode photos-album (default: date). "
                             "Options: date (year/month), year, category, format, smart (year/category)")
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

    # Check if scan produced any results
    if not os.path.exists(index_db):
        print()
        print("⚠️  No photos found. Please check the source path and try again.")
        return
    try:
        conn_check = sqlite3.connect(index_db)
        count_row = conn_check.execute("SELECT COUNT(*) FROM photos").fetchone()
        conn_check.close()
        if count_row[0] == 0:
            print()
            print("⚠️  No photos found. Please check the source path and try again.")
            return
    except sqlite3.OperationalError:
        print()
        print("⚠️  No photos found. Please check the source path and try again.")
        return

    # Check iCloud status
    if args.check_icloud or prefs["source_type"] == "photos_library":
        try:
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
        except sqlite3.OperationalError:
            pass  # photos_cloud_state column may not exist in file-system scans

    # List albums and exit (only for Photos Library sources)
    if args.list_albums:
        _list_albums(index_db)
        return

    # Album filtering
    album_filter = args.album_filter if hasattr(args, 'album_filter') else []
    exclude_album = args.exclude_album if hasattr(args, 'exclude_album') else []
    prefer_album = args.prefer_album if hasattr(args, 'prefer_album') else []

    if album_filter or exclude_album:
        _apply_album_filter(index_db, album_filter, exclude_album)

    # Pass prefer_album into prefs for strategy use
    if prefer_album:
        existing = prefs.get("prefer_folders", [])
        # Map album names to folder_tag values so they work with --strategy folder
        prefs["prefer_albums"] = prefer_album

    # Step 2-5: Route by organize mode
    mode = prefs.get("mode", "dedup")

    if mode == "dedup":
        # Dedup mode: detect duplicates → plan → confirm → apply
        print()
        print("🔍 Step 2/5: Detecting duplicates...")
        has_duplicates = run_detect(prefs, index_db, duplicates_csv)

        if not has_duplicates:
            print()
            print("✅ No duplicates found! Your library is clean.")
            return

        print()
        print("📝 Step 3/5: Generating move plan...")
        num_moves = run_plan(prefs, duplicates_csv, index_db, plan_csv, prefs["source_path"])
        print(f"  Generated {num_moves} planned moves")

    elif mode == "by-date":
        # By-date mode: organize photos into date-based folders
        print()
        print("📅 Step 2/5: Organizing by date...")
        num_moves = generate_by_date_plan(index_db, plan_csv, prefs["source_path"])
        print(f"  Generated {num_moves} planned moves (into YYYY/MM folders)")

    elif mode == "by-category":
        # By-category mode: organize photos by category
        print()
        print("🏷️  Step 2/5: Organizing by category...")
        num_moves = generate_by_category_plan(index_db, plan_csv, prefs["source_path"])
        print(f"  Generated {num_moves} planned moves (by category)")

    elif mode == "by-location":
        # By-location mode: organize by GPS location
        print()
        print("📍 Step 2/5: Organizing by location...")
        conn = sqlite3.connect(index_db)
        cursor = conn.execute("SELECT COUNT(*) FROM photos WHERE gps_latitude IS NOT NULL AND gps_latitude != ''")
        has_gps = cursor.fetchone()[0]
        conn.close()
        if has_gps == 0:
            print("  ⚠️  No GPS data found in photos. Cannot organize by location.")
            print("     Try 'by-date' or 'by-category' mode instead.")
            return
        print("  GPS-based location organization is not yet fully implemented.")
        print("  Photos with GPS data will be organized by city/region in a future version.")
        return

    elif mode == "photos-album":
        # Photos.app album organization mode
        if source_type != "photos_library":
            print("  ⚠️  --mode photos-album requires --source-type photos_library")
            print("     Point --source to a .photoslibrary bundle.")
            return

        organize_by = args.album_organize_by
        print()
        print(f"📁 Step 2/5: Organizing Photos.app albums by {organize_by}...")
        print(f"   Mode: {ALBUM_ORGANIZE_MODES.get(organize_by, organize_by)}")
        album_stats = organize_photos_albums(index_db, organize_by=organize_by, dry_run=args.dry_run)

        print()
        if album_stats["albums_created"] > 0 or args.dry_run:
            print("─" * 60)
            if args.dry_run:
                print(f"🏁 Dry run — no albums were created.")
            else:
                print(f"✅ Album organization complete!")
            print(f"   Albums created: {album_stats['albums_created']}")
            print(f"   Photos added: {album_stats['photos_added']}")
            if album_stats["errors"]:
                print(f"   Errors: {album_stats['errors']}")

        # Generate HTML report
        report_path = os.path.join(output_dir, "album_report.html")
        try:
            from generate_album_report import generate_album_report_html
            report_html = generate_album_report_html(
                index_db=index_db,
                organize_by=organize_by,
                stats=album_stats,
            )
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_html)
            print(f"   📊 Report: {report_path}")
            # Open report in browser
            import subprocess
            subprocess.Popen(["open", report_path])
        except Exception as e:
            print(f"   ⚠️  Could not generate report: {e}")

        return

    else:
        print(f"  ⚠️  Unknown mode: {mode}")
        return

    if num_moves == 0:
        print()
        print("✅ No moves needed! Photos are already organized.")
        return

    # Step 4: Preview & confirm
    print()
    print("👀 Step 4/5: Preview...")
    stats = show_preview(index_db, plan_csv)
    generate_manifest(prefs, plan_csv, stats, manifest_path)
    print(f"  Manifest saved to: {manifest_path}")

    # Generate HTML thumbnail preview
    preview_path = os.path.join(output_dir, "preview.html")
    try:
        from generate_preview import generate_preview_html
        html_content = generate_preview_html(
            duplicates_csv=duplicates_csv,
            index_db=index_db,
            move_plan_csv=plan_csv,
        )
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"  🖼️  Thumbnail preview: {preview_path}")
        # Open preview in browser
        import subprocess
        subprocess.Popen(["open", preview_path])
    except Exception as e:
        print(f"  ⚠️  Could not generate thumbnail preview: {e}")

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
