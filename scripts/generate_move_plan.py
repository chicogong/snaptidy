#!/usr/bin/env python3
"""Generate a move plan for duplicates with smart priority rules.

This script reads a duplicates CSV and the metadata index, then uses
configurable priority rules to decide which duplicate to KEEP and which
to move.  The "best" file in each group is kept in place; all others
are moved to a review folder.

Priority rules (configurable via --strategy):
  quality    — Keep highest resolution > largest file > best EXIF (default)
  oldest     — Keep the file with the earliest capture date (likely original)
  newest     — Keep the file with the latest modification date (likely edited)
  folder     — Keep files from preferred folders (specify via --prefer-folder)

Safety: No files are deleted.  Moved files go to a review folder.
Use --trash to move to macOS Trash instead of a custom folder.
"""

import argparse
import csv
import os
import sqlite3
import sys
import subprocess


def read_duplicates(dups_path: str) -> dict:
    """Read duplicates CSV, return {group_id: [file_path, ...]}."""
    groups = {}
    match_types = {}  # group_id -> match_type
    with open(dups_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Validate CSV has expected columns
        if reader.fieldnames is None or "file_path" not in (reader.fieldnames or []):
            print(f"Error: {dups_path} is not a valid duplicates CSV.", file=sys.stderr)
            print("       Expected columns: group_id, phash, file_path, match_type", file=sys.stderr)
            print("       If using --format human, re-run with --format csv (default).", file=sys.stderr)
            sys.exit(1)
        for row in reader:
            gid = row.get("group_id")
            fp = row.get("file_path")
            if not gid or not fp:
                continue  # Skip rows with missing data
            groups.setdefault(gid, []).append(fp)
            mt = row.get("match_type", "")
            if mt and gid not in match_types:
                match_types[gid] = mt
    return groups, match_types


def load_metadata_db(index_path: str) -> dict:
    """Load file metadata from SQLite DB.  Returns {file_path: {field: value}}."""
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM photos")
    metadata = {}
    for row in cursor:
        d = dict(row)
        metadata[d["file_path"]] = d
    conn.close()
    return metadata


def load_metadata_csv(index_path: str) -> dict:
    """Load file metadata from CSV.  Returns {file_path: {field: value}}."""
    metadata = {}
    with open(index_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            metadata[row.get("file_path", "")] = row
    return metadata


def score_file(meta: dict, strategy: str, prefer_folders: list = None) -> float:
    """Score a file for the 'keep' decision.  Higher score = more likely to keep."""
    score = 0.0
    prefer_folders = prefer_folders or []

    # Resolution score (0-100)
    try:
        w = int(meta.get("width") or 0)
        h = int(meta.get("height") or 0)
        pixels = w * h
        score += min(pixels / 1_000_000, 100)  # max 100 for 100MP+
    except (ValueError, TypeError):
        pass

    # File size score (0-50, larger = less compressed = better)
    try:
        size = int(meta.get("size_bytes") or 0)
        score += min(size / 1_000_000, 50)  # max 50 for 50MB+
    except (ValueError, TypeError):
        pass

    # EXIF completeness bonus (+30 if has EXIF)
    try:
        has_exif = int(meta.get("has_exif") or 0)
        if has_exif:
            score += 30
    except (ValueError, TypeError):
        pass

    # RAW format bonus (+20)
    ext = (meta.get("extension") or "").lower()
    if ext in ("dng", "cr2", "nef", "arw"):
        score += 20
    elif ext in ("heic", "heif"):
        score += 10  # HEIC is better than JPG

    # Non-screenshot bonus (+15)
    category = meta.get("category") or ""
    if category == "photo":
        score += 15
    elif category == "screenshot":
        score -= 20  # Penalize screenshots
    elif category == "wechat":
        score -= 10  # Penalize WeChat compressed images

    # Default folder priority (applied even without --prefer-folder)
    # Camera originals and organized folders are preferred over backups/downloads
    folder_tag = meta.get("folder_tag") or ""
    if folder_tag:
        ft_lower = folder_tag.lower()
        # High-priority folders (camera originals, organized archives)
        if any(kw in ft_lower for kw in ("dcim", "camera", "photos", "相册", "照片")):
            score += 25
        # Medium-priority folders (date-organized, events)
        elif any(kw in ft_lower for kw in ("202", "201", "200", "event", "旅行", "travel")):
            score += 10
        # Low-priority folders (backups, downloads, exports)
        elif any(kw in ft_lower for kw in ("backup", "备份", "download", "下载", "export", "导出")):
            score -= 15
        # Penalize WeChat/社交 folders
        elif any(kw in ft_lower for kw in ("wechat", "微信", "micro")):
            score -= 10

    # Explicit preferred folder bonus (+50, overrides default priority)
    if prefer_folders and folder_tag in prefer_folders:
        score += 50

    # Explicit preferred album bonus (+50)
    prefer_albums = (meta.get("_prefer_albums") or []) if isinstance(meta, dict) else []
    albums_str = meta.get("photos_albums") or ""
    if prefer_albums and albums_str:
        photo_albums = [a.strip() for a in albums_str.split(",") if a.strip()]
        if any(a in prefer_albums for a in photo_albums):
            score += 50

    # Strategy overrides
    if strategy == "oldest":
        # Earliest date gets bonus
        dt = meta.get("exif_datetime") or meta.get("file_mtime") or ""
        if dt:
            try:
                # Earlier dates get higher score
                from datetime import datetime
                dt_obj = datetime.fromisoformat(dt)
                # Invert: older = higher score (subtract from a large number)
                score += max(0, 1000 - dt_obj.timestamp() / 100000)
            except Exception:
                pass

    elif strategy == "newest":
        dt = meta.get("file_mtime") or ""
        if dt:
            try:
                from datetime import datetime
                dt_obj = datetime.fromisoformat(dt)
                score += min(dt_obj.timestamp() / 100000, 100)
            except Exception:
                pass

    elif strategy == "folder":
        # Strongly prefer specified folders
        if prefer_folders and folder_tag in prefer_folders:
            score += 200

    return score


def generate_plan(groups: dict, match_types: dict, metadata: dict, target_root: str,
                  strategy: str = "quality", prefer_folders: list = None,
                  use_trash: bool = False) -> list:
    """Generate a move plan using smart priority rules."""
    plan = []
    review_folder = "06_Duplicates_待确认删除" if not use_trash else "__TRASH__"
    seen_paths = set()  # Track files already added to plan (deduplicate across groups)

    # Human-readable labels for match types
    MATCH_TYPE_LABELS = {
        "exact_sha256": "identical SHA-256",
        "exact_phash": "identical pHash",
        "fuzzy_phash": "similar pHash",
        "scaled": "scaled duplicate",
        "cross_format": "cross-format duplicate",
        "burst_subsec": "burst photo",
        "apple_quality_vector": "Apple QL similar",
        "cnn_mobilenet": "CNN (MobileNet) similar",
    }

    for group_id, paths in groups.items():
        if len(paths) < 2:
            continue

        match_type = match_types.get(group_id, "")
        match_label = MATCH_TYPE_LABELS.get(match_type, match_type)

        # Score each file and pick the best one to keep
        scored = []
        for path in paths:
            meta = metadata.get(path, {})
            s = score_file(meta, strategy, prefer_folders)
            scored.append((s, path, meta))

        # Sort by score descending — highest score is the one to keep
        scored.sort(key=lambda x: -x[0])
        keep_path = scored[0][1]
        keep_meta = scored[0][2]

        # Build reason string
        keep_reason_parts = []
        try:
            w = keep_meta.get("width", "")
            h = keep_meta.get("height", "")
            if w and h:
                keep_reason_parts.append(f"{w}x{h}")
        except Exception:
            pass
        try:
            size = int(keep_meta.get("size_bytes") or 0)
            if size:
                keep_reason_parts.append(f"{size/1024/1024:.1f}MB")
        except Exception:
            pass
        keep_cat = keep_meta.get("category", "")
        if keep_cat:
            keep_reason_parts.append(keep_cat)
        keep_info = f"({', '.join(keep_reason_parts)})" if keep_reason_parts else ""

        for s, path, meta in scored[1:]:
            # Skip if already in plan from another group
            if path in seen_paths:
                continue
            # Build reason for moving
            move_reason_parts = [f"duplicate of {keep_path} {keep_info}"]
            if match_label:
                move_reason_parts.append(f"type: {match_label}")

            # Explain why this file was chosen to move
            move_meta_parts = []
            try:
                w = meta.get("width", "")
                h = meta.get("height", "")
                if w and h:
                    move_meta_parts.append(f"{w}x{h}")
            except Exception:
                pass
            try:
                size = int(meta.get("size_bytes") or 0)
                if size:
                    move_meta_parts.append(f"{size/1024/1024:.1f}MB")
            except Exception:
                pass
            move_cat = meta.get("category", "")
            if move_cat:
                move_meta_parts.append(move_cat)
            if move_meta_parts:
                move_reason_parts.append(f"this: ({', '.join(move_meta_parts)})")

            reason = " | ".join(move_reason_parts)

            # Compute destination
            try:
                rel = os.path.relpath(path, target_root)
            except ValueError:
                rel = os.path.basename(path)

            if use_trash:
                dest = os.path.join(target_root, review_folder, os.path.basename(path))
            else:
                dest = os.path.join(target_root, review_folder, rel)

            plan.append({
                "action": "move",
                "source_path": path,
                "target_path": dest,
                "reason": reason,
            })
            seen_paths.add(path)
    return plan


def write_plan(plan, plan_path: str) -> None:
    fieldnames = ["action", "source_path", "target_path", "reason"]
    with open(plan_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in plan:
            writer.writerow(entry)


def write_human_plan(plan, plan_path: str, metadata: dict = None) -> None:
    """Write human-readable move plan."""
    metadata = metadata or {}

    lines = []
    lines.append("=" * 72)
    lines.append(f"Move Plan — {len(plan)} actions")
    lines.append("=" * 72)
    lines.append("")

    total_reclaimable = 0
    for i, entry in enumerate(plan, 1):
        src = entry["source_path"]
        reason = entry.get("reason", "")

        # Get file metadata
        meta = metadata.get(src, {})
        size = 0
        try:
            size = int(meta.get("size_bytes") or 0)
        except (ValueError, TypeError):
            pass
        total_reclaimable += size

        # Format size
        if size >= 1_073_741_824:
            size_str = f"{size / 1_073_741_824:.1f} GB"
        elif size >= 1_048_576:
            size_str = f"{size / 1_048_576:.1f} MB"
        elif size >= 1_024:
            size_str = f"{size / 1_024:.1f} KB"
        else:
            size_str = f"{size} B"

        # Shorten path
        short_src = src
        if len(short_src) > 60:
            short_src = "..." + short_src[-57:]

        category = meta.get("category", "")
        info = "  ".join(filter(None, [size_str, category]))

        lines.append(f"{i:3}. MOVE {short_src}")
        if info:
            lines.append(f"     ({info})")
        if reason:
            # Truncate long reasons
            short_reason = reason if len(reason) <= 80 else reason[:77] + "..."
            lines.append(f"     Reason: {short_reason}")
        lines.append("")

    # Summary
    lines.append("-" * 72)
    if total_reclaimable >= 1_073_741_824:
        lines.append(f"Total reclaimable: {total_reclaimable / 1_073_741_824:.1f} GB")
    elif total_reclaimable >= 1_048_576:
        lines.append(f"Total reclaimable: {total_reclaimable / 1_048_576:.1f} MB")
    else:
        lines.append(f"Total reclaimable: {total_reclaimable / 1_024:.1f} KB")
    lines.append("")

    with open(plan_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate smart move plan for duplicates with priority rules")
    parser.add_argument("--duplicates", required=True, help="Path to duplicates CSV")
    parser.add_argument("--index", default="",
                        help="Path to metadata index (.db or .csv) for smart scoring")
    parser.add_argument("--plan", required=True, help="Path to output move plan CSV")
    parser.add_argument("--target-root", required=True, help="Root of your photo archive")
    parser.add_argument("--strategy", choices=["quality", "oldest", "newest", "folder"],
                        default="quality",
                        help="Priority strategy: quality (default), oldest, newest, folder")
    parser.add_argument("--prefer-folder", action="append", default=[],
                        help="Folder tags to prefer keeping (can specify multiple times)")
    parser.add_argument("--prefer-album", action="append", default=[],
                        help="Album names to prefer keeping (for Photos Library scans, can specify multiple)")
    parser.add_argument("--trash", action="store_true",
                        help="Move duplicates to macOS Trash instead of review folder")
    parser.add_argument("--format", choices=["csv", "human"], default="csv",
                        help="Output format: csv (default) or human (readable report)")
    args = parser.parse_args()

    dups, match_types = read_duplicates(os.path.abspath(args.duplicates))
    target_root = os.path.abspath(args.target_root)

    # Load metadata for smart scoring
    metadata = {}
    if args.index:
        index_path = os.path.abspath(args.index)
        if index_path.endswith(".db"):
            metadata = load_metadata_db(index_path)
        else:
            metadata = load_metadata_csv(index_path)

    # Inject prefer_albums into metadata so score_file can use it
    if args.prefer_album and metadata:
        for path, meta in metadata.items():
            meta["_prefer_albums"] = args.prefer_album

    plan = generate_plan(dups, match_types, metadata, target_root,
                         strategy=args.strategy,
                         prefer_folders=args.prefer_folder,
                         use_trash=args.trash)

    os.makedirs(os.path.dirname(os.path.abspath(args.plan)), exist_ok=True)
    if args.format == "human":
        write_human_plan(plan, os.path.abspath(args.plan), metadata)
    else:
        write_plan(plan, os.path.abspath(args.plan))

    # Space savings estimate
    total_reclaimable = 0
    for entry in plan:
        meta = metadata.get(entry["source_path"], {})
        try:
            total_reclaimable += int(meta.get("size_bytes") or 0)
        except (ValueError, TypeError):
            pass

    print(f"Generated move plan with {len(plan)} actions.")
    if total_reclaimable > 0:
        if total_reclaimable >= 1_073_741_824:
            print(f"  Reclaimable space: {total_reclaimable / 1_073_741_824:.1f} GB")
        elif total_reclaimable >= 1_048_576:
            print(f"  Reclaimable space: {total_reclaimable / 1_048_576:.1f} MB")
        else:
            print(f"  Reclaimable space: {total_reclaimable / 1_024:.1f} KB")
    if args.strategy != "quality":
        print(f"  Strategy: {args.strategy}")
    if args.prefer_folder:
        print(f"  Preferred folders: {', '.join(args.prefer_folder)}")
    if args.trash:
        print(f"  Mode: macOS Trash")


if __name__ == "__main__":
    main()
