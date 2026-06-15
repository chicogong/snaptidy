---
name: snaptidy
version: 2.0.0
description: |
  AI-powered photo & video organizer for macOS. Scan libraries, detect duplicates (SHA-256 exact + pHash perceptual), and generate safe move plans — without ever deleting your originals.
  Use this skill when you need to: scan and tidy large photo/video folders, find duplicate photos, deduplicate archives, organize a messy photo library, or generate a dedup report for human review.
  照片视频整理去重工具，支持SHA-256精确去重和pHash感知哈希，智能优先级规则，macOS回收站模式，微信/截图自动分类，SQLite存储10万+照片。
  Trigger phrases: "organize my photos", "find duplicate photos", "dedup my library", "tidy photo folder", "scan for duplicates", "整理照片", "去重", "整理相册", "重複写真削除", "写真整理", "사진 정리", "중복 사진"
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
        packages: [Pillow, piexif, imagehash]
---

# SnapTidy — Photo & Video Organizer

## When to Use

Invoke this skill when the user asks to:
- Organize or tidy up photo/video folders on macOS
- Find and remove duplicate photos
- Scan a photo library for duplicates
- Generate a dedup report or move plan
- Prepare a clean photo archive
- Free up disk space by finding and moving duplicates
- Consolidate photos from Android/iPhone/external drives
- 整理照片、去重、清理相册
- 重複写真を削除・整理する
- 사진 정리, 중복 사진 찾기

## Safety Rules (MANDATORY)

- **NEVER delete originals** — all scripts are read-only by default. `apply_move_plan.py` only moves files, never deletes.
- **NEVER permanently delete** — use macOS Trash mode (`--mode trash`) or move to review folder. Users can recover from Trash via Finder.
- **Stay out of Photos Libraries** — never enter `.photoslibrary` or `.photolibrary` directories. Always scan exported folders.
- **Operate only inside user-provided paths** — never scan system directories or disk roots.
- **Respect external backups** — skip directories named `Original_Backup` or similar.
- **Ask before moving** — ALWAYS present the move plan and get user confirmation before running `apply_move_plan.py`.
- **Ask which folder to prioritize** — when duplicates span multiple folders, ask the user which folder's photos they prefer to keep.
- **Ask about trash vs move** — offer the user a choice: move to review folder or move to macOS Trash (recoverable).

## Process

### Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

Dependencies: **Pillow** (image metadata), **piexif** (EXIF extraction), **imagehash** (perceptual hashing).
No pandas, no numpy, no heavy frameworks. SQLite is built into Python.

### Step 2: Scan the Photo Library

```bash
# Output to SQLite (recommended — fast for 100k+ photos, stores locally, no context bloat)
python3 scripts/scan_photos.py --input <photo_directory> --output photo_index.db

# Or output to CSV (fallback for small libraries)
python3 scripts/scan_photos.py --input <photo_directory> --output photo_index.csv
```

This extracts: file size, SHA-256, EXIF date, GPS location, camera make/model, dimensions, perceptual hash, auto-category (photo/screenshot/wechat/burst), and folder tag.

### Step 3: Find Duplicates

**Exact duplicates** (SHA-256, works with both .db and .csv):

```bash
python3 scripts/find_exact_duplicates.py --index photo_index.db --output duplicates_exact.csv
```

**Perceptually similar** (pHash, optional):

```bash
# Exact pHash match (default)
python3 scripts/find_similar_photos.py --index photo_index.db --output duplicates_similar.csv

# Fuzzy match with Hamming distance threshold (catches near-duplicates)
python3 scripts/find_similar_photos.py --index photo_index.db --output duplicates_similar.csv --threshold 5
```

### Step 4: Generate Move Plan (Smart Priority)

```bash
# Default: quality strategy — keep highest resolution, largest file, best EXIF
python3 scripts/generate_move_plan.py \
    --duplicates duplicates_exact.csv \
    --index photo_index.db \
    --plan move_plan.csv \
    --target-root <photo_directory>

# Keep files from a preferred folder (e.g., camera originals over WeChat downloads)
python3 scripts/generate_move_plan.py \
    --duplicates duplicates_exact.csv \
    --index photo_index.db \
    --plan move_plan.csv \
    --target-root <photo_directory> \
    --prefer-folder "DCIM" --prefer-folder "相机"

# Strategy options: quality (default), oldest, newest, folder
python3 scripts/generate_move_plan.py \
    --duplicates duplicates_exact.csv \
    --index photo_index.db \
    --plan move_plan.csv \
    --target-root <photo_directory> \
    --strategy oldest
```

### Step 5: Review and Apply

1. Open the generated `move_plan.csv` — verify every proposed move
2. Present the plan summary to the user
3. **Ask the user**: move to review folder OR move to macOS Trash?
4. Only after explicit confirmation, apply:

```bash
# Move to review folder (safe, files stay on disk)
python3 scripts/apply_move_plan.py --plan move_plan.csv --mode move

# Move to macOS Trash (recoverable via Finder > Put Back)
python3 scripts/apply_move_plan.py --plan move_plan.csv --mode trash
```

Every action is logged to `move_log.csv` with full audit trail.

## Smart Priority Rules

When deciding which duplicate to KEEP, SnapTidy scores files by:

| Factor | Weight | Rationale |
|--------|--------|-----------|
| Resolution (pixels) | High | Higher res = better quality |
| File size | Medium | Larger = less compressed |
| EXIF completeness | High | Has metadata = likely original |
| Format (RAW > HEIC > JPG) | Medium | Better format = better quality |
| Category (photo > wechat > screenshot) | Medium | Real photos over screenshots |
| Folder priority (auto) | Medium | DCIM/Photos > Backup/Downloads |
| Folder preference (manual) | High | User-specified priority folders |

Strategies: `--strategy quality` (default), `oldest`, `newest`, `folder`

## Auto-Categorization

| Category | Detected by |
|----------|------------|
| photo | Default for camera photos (including `IMG_*.JPG`) |
| screenshot | "screenshot", "截图", "截屏", "スクリーンショット", "스크린샷", "скриншот", or `IMG_\d+.PNG` (iOS) |
| wechat | "mmexport", "wx_camera_", "microMsg", "微信" |
| burst | "_HDR", "_burst", "连拍" (checked before screenshot) |
| video | Video file extensions |

## Storage & Performance

- **SQLite** (.db) — Recommended. Handles 100k+ photos efficiently. Query speed 400x faster than CSV for large libraries. Data stays local, no context bloat.
- **CSV** (.csv) — Fallback for small libraries. Compatible with Excel/Numbers.

## Supported Formats

| Type | Extensions |
|------|-----------|
| Images | jpg, jpeg, png, bmp, gif, tif, tiff, heic, heif, webp |
| RAW | dng, cr2, nef, arw |
| Videos | mov, mp4, m4v, avi, mkv, 3gp, mpg, mpeg, hevc, wmv, flv |

## Troubleshooting

- **Permission denied**: Enable Full Disk Access (System Settings → Privacy & Security → Full Disk Access)
- **No EXIF data**: Screenshots and downloaded photos lack EXIF. Scan still works.
- **pHash false positives**: Solid-color or very simple images produce identical pHash. Use SHA-256 as primary method, pHash as secondary.
- **Large library slow scan**: Use SQLite output (not CSV). Index is stored locally between runs.
- **External drive**: Scan directly from the external drive path. Use `--prefer-folder` for the drive's photo folder.
