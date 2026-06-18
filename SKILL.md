---
name: snaptidy
version: 3.14.0
description: |
  AI-powered photo & video organizer for macOS. Detect duplicates (SHA-256 exact + pHash perceptual + scaled + cross-format + burst + Apple ML vectors + CNN), assess quality (7-dimension scoring), organize by date/category/location, create Photos.app albums, reverse geocode GPS, edit EXIF, handle iCloud placeholders, convert formats, and more. Zero-install core (Python stdlib only).
  Trigger: "organize my photos", "find duplicate photos", "dedup my library", "tidy photo folder", "import photos", "整理照片", "去重", "整理相册", "HEIC去重", "写真整理", "사진 정리", "照片库健康", "library stats", "按地点整理", "逆地理编码", "移除GPS", "EXIF编辑", "照片质量", "Live Photo", "corrupted photo", "损坏图片", "fix date", "修正日期", "backup verify", "备份验证", "iCloud优化", "check icloud", "照片旋转", "格式转换", "JPEG转WEBP", "GPS推断", "动图检测", "bad extension", "扩展名校验"
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

Organize/tidy photo folders, find/remove duplicates, scan Photos.app library, detect scaled/cross-format/burst duplicates, generate move plans, preview with HTML thumbnails, undo moves, check iCloud status, scan Android/external drives, import into Photos.app with dedup, read shared albums, filter by album, create albums by date/category/format, reverse geocoding (GPS→place names), EXIF editing, quality assessment, Live Photo detection, timeline viewer, Google Takeout import, GPX geotagging, event clustering, video dedup, smart rename, corrupted file detection, bad extension detection, date correction, backup verification, iCloud optimization.

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

# Step 1: Scan photos (folders or Photos.app library)
python3 scripts/scan_photos.py --source ~/Pictures/Export --output ./photo_index.db

# Step 2: Find duplicates (exact + perceptual + scaled + cross-format)
python3 scripts/find_exact_duplicates.py --index ./photo_index.db --output ./duplicates.csv
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --detect-all

# Step 3: Assess quality (7 dimensions: sharpness/exposure/contrast/resolution/format/filesize/EXIF)
python3 scripts/assess_quality.py --index ./photo_index.db

# Step 4: Generate move plan with strategy
python3 scripts/generate_move_plan.py --duplicates ./similar.csv --index ./photo_index.db \
    --plan ./move_plan.csv --target-root ~/review --strategy quality

# Step 5: Preview with HTML thumbnails
python3 scripts/generate_preview.py --duplicates ./similar.csv --index ./photo_index.db --output ./preview.html

# Apply (with undo support)
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --mode trash
```

## Strategy Choices

| Strategy | Keeps | Best for |
|----------|-------|----------|
| `quality` (default) | Best quality score (7-dimension) | General cleanup |
| `oldest` | Earliest capture date | Keep originals |
| `newest` | Latest modification date | Keep final edits |
| `folder` | Files from preferred folder | Keep camera originals |

## Process

1. **Scan** — `scan_photos.py` (folders) or `scan_photos_library.py` (Photos.app)
2. **Find duplicates** — `find_exact_duplicates.py` (SHA-256) or `find_similar_photos.py --detect-all` (8 modes)
3. **Assess quality** — `assess_quality.py` (7-dimension scoring)
4. **Detect issues** — `detect_corrupted.py`, `detect_bad_extensions.py`, `detect_live_photos.py`
5. **Review & decide** — `generate_review.py` → Interactive HTML page with smart rules
6. **Generate plan** — `generate_move_plan.py --strategy quality|oldest|newest|folder`
7. **Apply** — `apply_move_plan.py --mode move|trash|photos-trash` (undo via `--undo`)

## CLI Conventions

- `--source` (`--input` / `--library`, `-i` for folders) — photo source
- `--index` (`-i`) — SQLite metadata index (consumed by dedup/report tools)
- `--output` (`-o`, also `--report` for HTML producers) — output path

For detailed feature tables, detection algorithms, priority rules, import workflow, iCloud integration, performance benchmarks, and troubleshooting, see `references/` (especially `references/features.md`).
