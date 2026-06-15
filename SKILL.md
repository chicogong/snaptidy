---
name: snaptidy
version: 3.1.0
description: |
  AI-powered photo & video organizer for macOS. Scan libraries, detect duplicates (SHA-256 exact + pHash perceptual + scaled + cross-format), generate safe move plans, preview with HTML thumbnails, and undo if needed — without ever deleting your originals.
  Use this skill when you need to: scan and tidy large photo/video folders, find duplicate photos, deduplicate archives, organize a messy photo library, generate a dedup report for human review, preview duplicates before acting, or undo a move operation.
  照片视频整理去重工具，支持SHA-256精确去重、pHash感知哈希、缩放去重、跨格式去重（HEIC↔JPEG）、连拍检测，HTML缩略图预览，一键撤销操作，iCloud状态检测，Android/外置硬盘扫描，交互式整理流程，15+语言识别，智能优先级规则，Photos.app数据库直读，PyObjC安全删除，SQLite存储10万+照片。
  Trigger phrases: "organize my photos", "find duplicate photos", "dedup my library", "tidy photo folder", "scan for duplicates", "整理照片", "去重", "整理相册", "重複写真削除", "写真整理", "사진 정리", "중복 사진", "organiser mes photos", "Fotos organisieren", "organizar fotos", "정리 사진"
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
- Preview duplicates with HTML thumbnails before acting
- Undo a previous move operation
- Check iCloud download status of photos
- Scan Android phone or external drive for photos
- Run an interactive organize workflow
- Prepare a clean photo archive
- Free up disk space by finding and moving duplicates
- Consolidate photos from Android/iPhone/external drives
- 整理照片、去重、清理相册
- 重複写真を削除・整理する
- 사진 정리, 중복 사진 찾기
- Organiser mes photos, supprimer les doublons
- Fotos organisieren, Duplikate finden
- Organizar fotos, eliminar duplicados

## Safety Rules (MANDATORY)

- **NEVER delete originals** — all scripts are read-only by default. `apply_move_plan.py` only moves files, never deletes.
- **NEVER permanently delete** — use macOS Trash mode (`--mode trash`) or move to review folder. Users can recover from Trash via Finder.
- **Stay out of Photos Libraries when using scan_photos.py** — use `scan_photos_library.py` instead for `.photoslibrary` bundles.
- **Operate only inside user-provided paths** — never scan system directories or disk roots.
- **Respect external backups** — skip directories named `Original_Backup` or similar.
- **Ask before moving** — ALWAYS present the move plan and get user confirmation before running `apply_move_plan.py`.
- **Ask which folder to prioritize** — when duplicates span multiple folders, ask the user which folder's photos they prefer to keep.
- **Ask about trash vs move** — offer the user a choice: move to review folder or move to macOS Trash (recoverable).
- **Fast/Safe path confirmation** — 1-9 moves: brief `[Y/n]` confirmation. 10+ moves: require explicit `"yes"` to proceed. Always present summary stats before confirming.
- **Undo support** — always inform the user that `--undo` is available after a move operation. Undo records auto-expire after 30 days.

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

**Option C: One-command interactive workflow** (recommended for first-time users):

```bash
# Interactive mode — asks for preferences step by step
python3 scripts/organize_photos.py --source ~/Pictures/Export --interactive

# Non-interactive with dry-run (preview only)
python3 scripts/organize_photos.py --source ~/Pictures/Export --dry-run --detect-all

# Detect external drives and Android devices
python3 scripts/organize_photos.py --source /any --detect-sources

# Check iCloud download status before scanning
python3 scripts/organize_photos.py --source ~/Pictures/Export --check-icloud
```

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

### Step 4: Preview Duplicates (HTML)

Before generating a move plan, preview duplicates visually:

```bash
python3 scripts/generate_preview.py \
    --duplicates duplicates_similar.csv \
    --index photo_index.db \
    --output preview.html

# With move plan overlay (shows KEEP/MOVE badges)
python3 scripts/generate_preview.py \
    --duplicates duplicates_similar.csv \
    --index photo_index.db \
    --plan move_plan.csv \
    --output preview.html
```

The preview shows:
- **Summary stats bar** (total groups, images, match type breakdown)
- **Per-group cards** with thumbnails, filename, dimensions, size, category, folder, EXIF, camera
- **Green KEEP badge** for files to keep, **orange MOVE badge** for files to move
- Works with any duplicates CSV + index DB + optional move plan CSV

### Step 5: Generate Move Plan (Smart Priority)

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

### Step 6: Review and Apply

1. Open the generated `move_plan.csv` — verify every proposed move
2. Or open `preview.html` for visual review with thumbnails
3. Present the plan summary to the user
4. **Ask the user**: move to review folder OR move to macOS Trash OR remove from Photos.app?
5. Only after explicit confirmation, apply:

```bash
# Move to review folder (safe, files stay on disk)
python3 scripts/apply_move_plan.py --plan move_plan.csv --mode move

# Move to macOS Trash (recoverable via Finder > Put Back)
python3 scripts/apply_move_plan.py --plan move_plan.csv --mode trash

# Remove from Photos.app via PyObjC (keeps library consistent)
python3 scripts/apply_move_plan.py --plan move_plan.csv --mode photos-trash
```

Every action is logged to `move_log.csv` with full audit trail.

### Step 7: Undo (if needed)

If you need to reverse the last move operation:

```bash
python3 scripts/apply_move_plan.py --plan move_plan.csv --undo
```

Undo records are stored in `undo_records/` subdirectory as JSON files. Each record:
- Tracks all source → destination mappings
- Has a 30-day expiry (warns if expired)
- Reverses operations in reverse order (last operation undone first)
- Trash operations cannot be undone from CLI — user must use Finder > Put Back
- Record is removed after successful undo

## Interactive Workflow (organize_photos.py)

For a one-command pipeline that asks for preferences and runs everything:

```bash
# Full interactive mode
python3 scripts/organize_photos.py --source ~/Pictures/Export --interactive

# Non-interactive with all detection methods
python3 scripts/organize_photos.py \
    --source ~/Pictures/Export \
    --dedup-method all \
    --strategy quality \
    --trash-mode trash \
    --dry-run
```

### Interactive Prompts

When using `--interactive`, the workflow asks:

1. **Source type** — folder on disk or Photos.app library
2. **Organize mode** — dedup / by-date / by-location / by-category (currently only dedup is implemented)
3. **Dedup method** — exact / phash / scaled / cross-format / burst / all
4. **Strategy** — quality / oldest / newest / folder
5. **Preferred folder** — which folder's photos to keep (e.g., DCIM, 相册)
6. **Trash mode** — move to review folder / macOS Trash / Photos.app delete

### Confirmation Model (Fast/Safe Path)

- **Fast path** (1-9 moves): brief `[Y/n]` confirmation
- **Safe path** (10+ moves): requires typing explicit `"yes"` to proceed
- A manifest (`plan_manifest.json`) is generated with full details for review
- Use `--dry-run` to preview without making any changes

### External Source Detection

```bash
# Detect connected Android devices and external drives with photos
python3 scripts/organize_photos.py --source /any --detect-sources
```

Detects:
- **Android phones** via DCIM folder at `/Volumes/Android`, `/Volumes/Galaxy`, `/Volumes/Pixel`, etc.
- **External drives** with DCIM, Photos, or Pictures folders
- **iCloud status** — checks for `.icloud` companion files and `com.apple.iCloud.syncState` xattr

### iCloud Integration

```bash
# Check iCloud download status before scanning
python3 scripts/organize_photos.py --source ~/Pictures/Export --check-icloud
```

- Detects iCloud-only files (not fully downloaded to local disk)
- Reports count of iCloud-only files that will be skipped during move operations
- For Photos.app library scans, uses `photos_cloud_state` field from Photos.sqlite
- Can trigger download via `brctl download` (macOS only)

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

## Auto-Categorization (15+ Languages)

| Category | Detected by |
|----------|------------|
| photo | Default for camera photos (including `IMG_*.JPG`) |
| screenshot | English, 中文, 日本語, 한국어, Русский, Français, Deutsch, Español, Italiano, Português, Nederlands, ไทย, Tiếng Việt, Bahasa, or iOS `IMG_\d+.PNG`, or Photos.app screenshot flag |
| wechat | "mmexport", "wx_camera_", "microMsg", "微信", "KakaoTalk", "LINE_" |
| burst | "_HDR", "_burst", "连拍", "連拍", "버스트", "연속", "連写", "バースト", or HDR flag from Photos.app |
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
- **HTML Preview** — Standalone HTML file with embedded thumbnails. Open in any browser.

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
- **Undo expired**: Undo records expire after 30 days. Check `undo_records/` for existing records.
- **iCloud files skipped**: iCloud-only files (not downloaded locally) are skipped during move. Use `--check-icloud` to detect them, or download via `brctl download`.
- **Android not detected**: Ensure Android File Transfer is installed and the phone is unlocked. Check `/Volumes/` for mount points.
