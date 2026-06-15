---
name: snaptidy
version: 3.0.0
description: |
  AI-powered photo & video organizer for macOS. Scan libraries, detect duplicates (SHA-256 exact + pHash perceptual + scaled + cross-format), and generate safe move plans — without ever deleting your originals.
  Use this skill when you need to: scan and tidy large photo/video folders, find duplicate photos, deduplicate archives, organize a messy photo library, or generate a dedup report for human review.
  照片视频整理去重工具，支持SHA-256精确去重、pHash感知哈希、缩放去重（同一照片不同尺寸）、跨格式去重（HEIC↔JPEG）、连拍检测，智能优先级规则，Photos.app数据库直读，PyObjC安全删除，SQLite存储10万+照片。
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
        packages: [Pillow, piexif, imagehash, pillow-heif]
---

# SnapTidy — Photo & Video Organizer

## When to Use

Invoke this skill when the user asks to:
- Organize or tidy up photo/video folders on macOS
- Find and remove duplicate photos
- Scan a photo library for duplicates (file folders OR Photos.app library)
- Detect scaled duplicates (same photo at different resolutions)
- Detect cross-format duplicates (HEIC + JPEG of same photo)
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
- **Stay out of Photos Libraries when using scan_photos.py** — use `scan_photos_library.py` instead for `.photoslibrary` bundles.
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

Core dependencies: **Pillow** (image metadata), **piexif** (EXIF extraction), **imagehash** (perceptual hashing).
Optional: **pillow-heif** (HEIC/HEIF support), **pyobjc-framework-Photos** (Photos.app deletion).
No pandas, no numpy, no heavy frameworks. SQLite is built into Python.

### Step 2: Scan the Photo Library

**Option A: File-system scan** (for exported folders, external drives, Android imports):

```bash
python3 scripts/scan_photos.py --input <photo_directory> --output photo_index.db
```

**Option B: Photos.app library scan** (for macOS Photos Library — reads Photos.sqlite):

```bash
python3 scripts/scan_photos_library.py --library ~/Pictures/Photos\ Library.photoslibrary --output photo_index.db
```

The library scan extracts additional metadata: album membership, favorite/hidden flags, screenshot detection, duplicate visibility, iCloud state. Output format is compatible with all downstream scripts.

### Step 3: Find Duplicates

**Exact duplicates** (SHA-256, works with both .db and .csv):

```bash
python3 scripts/find_exact_duplicates.py --index photo_index.db --output duplicates_exact.csv
```

**Perceptually similar** (pHash + scaled + cross-format + burst):

```bash
# All detection methods (recommended — catches all duplicate types)
python3 scripts/find_similar_photos.py --index photo_index.db --output duplicates_similar.csv --detect-all

# Individual methods:
python3 scripts/find_similar_photos.py --index photo_index.db --output similar.csv                      # pHash only (default)
python3 scripts/find_similar_photos.py --index photo_index.db --output scaled.csv --detect-scaled       # Scaled duplicates
python3 scripts/find_similar_photos.py --index photo_index.db --output cross.csv --detect-cross-format  # Cross-format (HEIC↔JPEG)
python3 scripts/find_similar_photos.py --index photo_index.db --output burst.csv --detect-bursts        # Burst via SubSecTime

# Fuzzy pHash with Hamming distance threshold
python3 scripts/find_similar_photos.py --index photo_index.db --output similar.csv --threshold 5
```

**Detection types explained:**

| Type | Flag | Detects | Example |
|------|------|---------|---------|
| pHash | (default) | Identical/similar perceptual hash | Edits, crops |
| Scaled | `--detect-scaled` | Same photo at different resolutions | 4000x3000 vs 800x600 WeChat |
| Cross-format | `--detect-cross-format` | Same photo in different formats | iPhone HEIC + exported JPEG |
| Burst | `--detect-bursts` | Burst photos via SubSecTime | Multiple shots in same second |

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

Move plan now includes match type labels: "identical pHash", "scaled duplicate", "cross-format duplicate", "burst photo".

### Step 5: Review and Apply

1. Open the generated `move_plan.csv` — verify every proposed move
2. Present the plan summary to the user
3. **Ask the user**: move to review folder OR move to macOS Trash OR remove from Photos.app?
4. Only after explicit confirmation, apply:

```bash
# Move to review folder (safe, files stay on disk)
python3 scripts/apply_move_plan.py --plan move_plan.csv --mode move

# Move to macOS Trash (recoverable via Finder > Put Back)
python3 scripts/apply_move_plan.py --plan move_plan.csv --mode trash

# Remove from Photos.app via PyObjC (keeps library consistent)
python3 scripts/apply_move_plan.py --plan move_plan.csv --mode photos-trash
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
| Photos.app favorite | High | Never move favorited photos |

Strategies: `--strategy quality` (default), `oldest`, `newest`, `folder`

## Auto-Categorization

| Category | Detected by |
|----------|------------|
| photo | Default for camera photos (including `IMG_*.JPG`) |
| screenshot | "screenshot", "截图", "截屏", "スクリーンショット", "스크린샷", "скриншот", or `IMG_\d+.PNG` (iOS), or Photos.app screenshot flag |
| wechat | "mmexport", "wx_camera_", "microMsg", "微信" |
| burst | "_HDR", "_burst", "连拍" (checked before screenshot), or HDR flag from Photos.app |
| video | Video file extensions |

## Detection Methods Detail

### Scaled Duplicate Detection

Finds the same photo saved at different resolutions (e.g., original 4032x3024 vs WeChat compressed 1080x1920).

Algorithm:
1. Group images by aspect ratio (within 1.5% tolerance)
2. Check dimension ratio for simple scaling relationships (2x, 3x, 4x, etc.)
3. Verify with pHash similarity (Hamming distance ≤ 10)

### Cross-Format Duplicate Detection

Finds the same photo saved in different formats (e.g., iPhone HEIC original + JPEG export).

Algorithm:
1. Group images by aspect ratio
2. Within same group, find pairs with different format families
3. Check dimensions are within 0.5% (format conversion may crop 1px)
4. Verify with pHash similarity (Hamming distance ≤ 12)

### Burst Detection via SubSecTime

Groups burst photos taken within the same second using EXIF SubSecTimeOriginal.

Algorithm:
1. Extract sub-second timestamps from EXIF
2. Group photos by identical DateTimeOriginal
3. Photos with different SubSecTime in the same second are classified as burst

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
- **HEIC not readable**: Install `pillow-heif` (`pip install pillow-heif`) for full HEIC/HEIF support.
- **Photos.app scan fails**: Ensure the .photoslibrary bundle is not being used by Photos.app at the same time. Close Photos.app first.
- **PyObjC deletion fails**: Ensure `pyobjc-framework-Photos` is installed and Photos.app is running.
- **Large library slow scan**: Use SQLite output (not CSV). Index is stored locally between runs.
- **External drive**: Scan directly from the external drive path. Use `--prefer-folder` for the drive's photo folder.
