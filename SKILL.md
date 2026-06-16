---
name: snaptidy
version: 3.4.0
description: |
  AI-powered photo & video organizer for macOS. Detect duplicates using SHA-256 exact + pHash perceptual + scaled + cross-format (HEIC↔JPEG) + burst + Apple Quality Vector + CNN. Scan file folders or Photos.app library. Import from external drives/Android into Photos.app with automatic dedup. Organize by date/category, interactive workflow, HTML thumbnail preview, undo support, iCloud/Android/external drive detection, shared album reading, album-aware filtering, smart priority rules with album/folder preference, Fast/Safe path confirmation, SQLite storage for 100k+ photos.
  Trigger: "organize my photos", "find duplicate photos", "dedup my library", "tidy photo folder", "import photos", "import from Android", "整理照片", "去重", "整理相册", "HEIC去重", "写真整理", "사진 정리", "按日期整理照片", "organize by date", "导入照片", "清理相册", "album dedup"
author: chicogong
license: MIT
homepage: https://github.com/chicogong/snaptidy
compatibility: "Claude Code, Cursor, Windsurf, OpenClaw, WorkBuddy, Cline, Aider"
metadata:
  openclaw:
    always: false
    emoji: "🗂️"
    os:
      - darwin
    requires:
      bins:
        - python3
    install:
      - kind: pip
        packages: [Pillow, piexif, imagehash, pillow-heif]
---

# SnapTidy — Photo & Video Organizer

## When to Use

Organize/tidy photo folders, find/remove duplicates, scan Photos.app library, detect scaled/cross-format/burst duplicates, generate move plans, preview with HTML thumbnails, undo moves, check iCloud status, scan Android/external drives, import into Photos.app with dedup, read shared albums, filter by album.

**Triggers:** 整理照片 · 去重 · 整理相册 · 重複写真を削除 · 사진 정리 · Organiser mes photos · Fotos organisieren · Organizar fotos · 清理相册

## Safety Rules — MANDATORY

- **NEVER delete originals** — all scripts are read-only by default
- **NEVER permanently delete** — use Trash mode or move to review folder
- **Ask before moving** — ALWAYS present plan and get confirmation
- **Fast/Safe path** — 1-9 moves: `[Y/n]`; 10+ moves: require explicit `"yes"`
- **Undo available** — `--undo` reverses last operation (30-day expiry)
- **Shared albums are read-only** — Apple blocks all programmatic writes to shared albums

## Quick Start

```bash
pip install -r requirements.txt

# Step 1: See what albums exist in Photos Library
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary --list-albums

# Step 2: Clean duplicates in a specific album (keep originals = oldest)
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --album-filter "我的旅行" --strategy oldest --dry-run

# Step 3: Full interactive workflow
python3 scripts/organize_photos.py --source ~/Pictures/Export --interactive

# Import from external drive into Photos.app
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --dry-run
```

## Strategy Choices — How to Decide Which Duplicate to Keep

| Strategy | Keeps | Best for |
|----------|-------|----------|
| `quality` (default) | Highest resolution + largest file + best EXIF | General cleanup — always keep the best version |
| `oldest` | Earliest capture date | Keep the original, remove later copies/edits |
| `newest` | Latest modification date | Keep the final edit, remove older versions |
| `folder` + `--prefer-folder DCIM` | Files from preferred folder | Keep camera originals, remove Backup/Download copies |
| `folder` + `--prefer-album "Favorites"` | Files from preferred album | Keep photos in your favorite album, remove duplicates elsewhere |

## Album-Aware Dedup — Clean Specific Albums

```bash
# List available albums first
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary --list-albums

# Only process duplicates within "旅行照片" album
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --album-filter "旅行照片" --dry-run

# Skip "Screenshots" album from dedup
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --exclude-album "Screenshots" --dry-run

# Prefer keeping photos from "Favorites" album
python3 scripts/generate_move_plan.py --duplicates dup.csv --index index.db \
  --plan plan.csv --target-root ~/review --strategy folder --prefer-album "Favorites"
```

## Process

1. **Scan** — `scan_photos.py` (folders) or `scan_photos_library.py` (Photos.app)
2. **Find duplicates** — `find_exact_duplicates.py` (SHA-256) or `find_similar_photos.py --detect-all` (8 modes)
3. **Preview** — `generate_preview.py` → HTML thumbnails with KEEP/MOVE badges
4. **Generate plan** — `generate_move_plan.py --strategy quality|oldest|newest|folder`
5. **Review & apply** — `apply_move_plan.py --mode move|trash` (undo via `--undo`)

For detailed detection algorithms, priority rules, import workflow, iCloud integration, performance benchmarks, and troubleshooting, see `references/`.
