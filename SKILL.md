---
name: snaptidy
version: 3.13.0
description: |
  AI-powered photo & video organizer for macOS. Detect duplicates using SHA-256 exact + pHash perceptual + scaled + cross-format (HEIC↔JPEG) + burst + Apple Quality Vector + CNN. Scan file folders or Photos.app library. Import from external drives/Android into Photos.app with automatic dedup. Organize by date/category/location, create albums in Photos.app, library health & insights report, HTML before/after report, interactive workflow, HTML thumbnail preview, undo support, iCloud/Android/external drive detection, shared album reading, album-aware filtering, smart priority rules with album/folder preference, Fast/Safe path confirmation, SQLite storage for 100k+ photos, reverse geocoding (GPS→place names), EXIF editing (strip GPS/set dates/write tags), interactive review page with smart strategy rules (metadata/oldest/newest/resolution/preferred album/best quality), quality assessment (blur/brightness/contrast → 0-100 score integrated with dedup), Live Photo detection (keep pairs together during dedup), orphan RAW cleanup, interactive timeline viewer, Photos.app vs file-system library compare, Google Takeout import with metadata merge, GPX geotagging, event clustering by time+location, video dedup via frame sampling+pHash, smart rename by EXIF date/camera/location templates, corrupted image/video detection (layered Pillow verify+load, ffmpeg probe), photo date correction from filename/neighbors/mtime, backup verification (quick or SHA-256 full), duplicate folder detection (Jaccard similarity), space what-if analysis, iCloud optimization handling (detect/skip/download placeholder thumbnails, disk space safety check, batch download with progress), batch EXIF orientation rotation fix, format conversion (JPEG/HEIC→WEBP/AVIF with 30-50% savings), GPS neighbor inference (infer missing GPS from temporally adjacent photos), animated image detection (GIF/animated WebP/APNG), decompression bomb protection (60MP limit), AVIF format support.
  Trigger: "organize my photos", "find duplicate photos", "dedup my library", "tidy photo folder", "import photos", "import from Android", "整理照片", "去重", "整理相册", "HEIC去重", "写真整理", "사진 정리", "按日期整理照片", "organize by date", "导入照片", "清理相册", "album dedup", "创建相册", "归类相册", "相册分类", "按类别整理", "按格式分类", "album organization", "organize albums", "photos album", "相册报告", "整理报告", "照片库健康", "library health", "library stats", "照片统计", "library insights", "照片库分析", "按地点整理", "organize by location", "逆地理编码", "reverse geocode", "移除GPS", "strip GPS", "EXIF编辑", "EXIF edit", "照片审核", "photo review", "review duplicates", "审核重复", "照片质量", "photo quality", "quality assessment", "Live Photo", "orphan RAW", "timeline", "照片时间线", "library compare", "Google Takeout", "GPX geotag", "event clustering", "照片事件", "video dedup", "视频去重", "smart rename", "照片重命名", "corrupted photo", "损坏图片", "fix date", "修正日期", "backup verify", "备份验证", "duplicate folder", "重复文件夹", "what if", "空间分析", "iCloud", "iCloud placeholder", "iCloud download", "brctl download", "optimize storage", "iCloud优化", "check icloud", "icloud check", "iCloud空间不足", "rotate photo", "EXIF orientation", "照片旋转", "方向纠正", "照片方向", "convert format", "格式转换", "WEBP", "AVIF", "JPEG转WEBP", "save space", "节省空间", "fix gps", "GPS推断", "GPS缺失", "missing GPS", "animated", "动图检测", "GIF去重"
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

Organize/tidy photo folders, find/remove duplicates, scan Photos.app library, detect scaled/cross-format/burst duplicates, generate move plans, preview with HTML thumbnails, undo moves, check iCloud status, scan Android/external drives, import into Photos.app with dedup, read shared albums, filter by album, **create albums in Photos.app by date/category/format**, **HTML before/after diff report**, **library health & insights (read-only stats)**, **reverse geocoding (GPS→place names)**, **EXIF editing (strip GPS/set dates/write tags)**, **organize by location (Country/Region/City/)**, **interactive review page with smart strategy rules**, **quality assessment (blur/brightness/contrast → dedup integration)**, **Live Photo detection (keep pairs together)**, **orphan RAW cleanup**, **interactive timeline viewer**, **Photos.app vs file-system compare**, **Google Takeout import**, **GPX geotagging**, **event clustering**, **video dedup**, **smart rename**, **corrupted image/video detection**, **photo date correction from filename/neighbors/mtime**, **backup verification**, **duplicate folder detection**, **space what-if analysis**, **iCloud optimization handling (detect/skip/download placeholder thumbnails, disk space safety check, batch download with progress)**.

**Triggers:** 整理照片 · 去重 · 整理相册 · 重複写真を削除 · 사진 정리 · Organiser mes photos · Fotos organisieren · Organizar fotos · 清理相册 · 照片库健康 · library stats · 按地点整理 · 逆地理编码 · 移除GPS · EXIF编辑 · 照片质量 · Live Photo · 时间线 · 视频去重 · 照片重命名 · 照片事件 · 损坏图片 · 修正日期 · 备份验证 · 重复文件夹 · 空间分析 · iCloud优化 · check icloud · 照片旋转 · 方向纠正 · 格式转换 · JPEG转WEBP · 节省空间 · GPS推断 · 动图检测

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

# Step 4: Organize Photos.app into date-based albums
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by date

# Step 5: Organize by category (Screenshots, Photos, etc.)
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by category --dry-run

# Step 6: Organize by location (Country/Region/City/)
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-location --dry-run

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
3. **Assess quality** — `assess_quality.py` (blur/brightness/contrast → DB, used by dedup & review)
4. **Detect Live Photos** — `detect_live_photos.py` (pairs HEIC+MOV, protects during dedup)
5. **Review & decide** — `generate_review.py` → Interactive HTML page with smart rules
6. **Generate plan** — `generate_move_plan.py --strategy quality|oldest|newest|folder`
7. **Apply** — `apply_move_plan.py --mode move|trash|photos-trash` (undo via `--undo`)

## v3.9 New Features

| Script | Trigger | What it does |
|--------|---------|-------------|
| `assess_quality.py` | "照片质量", "quality assessment" | Blur/brightness/contrast → Q0-100 score, auto-used in dedup strategy & review page |
| `detect_live_photos.py` | "Live Photo" | Pairs HEIC+MOV, prevents splitting during dedup |
| `find_orphan_raw.py` | "orphan RAW" | RAW without JPEG companion (or vice versa) |
| `generate_timeline.py` | "timeline", "照片时间线" | Interactive HTML timeline, zoom year/month/day |
| `compare_libraries.py` | "library compare" | Photos.app vs file-system, SHA-256 + filename matching |
| `import_google_takeout.py` | "Google Takeout" | Import Google Photos export, merge JSON metadata to EXIF |
| `gpx_geotag.py` | "GPX geotag" | Assign GPS from GPX track files, interpolation |
| `cluster_events.py` | "event clustering", "照片事件" | Auto-group photos by time + location |
| `find_similar_videos.py` | "video dedup", "视频去重" | Frame sampling + pHash for video duplicates |
| `rename_photos.py` | "smart rename", "照片重命名" | Rename by EXIF date/camera/location: `{date}_{camera}_{seq}` |

## v3.10 New Features

| Script | Trigger | What it does |
|--------|---------|-------------|
| `detect_corrupted.py` | "corrupted photo", "损坏图片" | Find broken/truncated images, unplayable videos; layered Pillow verify+load, ffmpeg probe; parallel |
| `fix_dates.py` | "fix date", "修正日期" | Fix missing EXIF dates from filename (15+ patterns), neighbor photos, file mtime; supports --dry-run, --write-exif |
| `verify_backup.py` | "backup verify", "备份验证" | Verify backup completeness; quick (filename+size) or full (SHA-256); coverage % |
| `find_duplicate_folders.py` | "duplicate folder", "重复文件夹" | Find similar folders by Jaccard content similarity; near-duplicate grouping |
| `library_stats.py --what-if` | "what if", "空间分析" | "How much space would I save if I delete screenshots/duplicates/RAW?" |
| `--create-event-albums` | "event album" | Create Photos.app albums from cluster_events.py results |

## v3.11 New Features

| Feature | Description |
|---------|-------------|
| `--parallel N` | Parallel scanning (scan_photos.py, assess_quality.py) — 2.9x speedup |
| `--incremental` | Incremental scan — skip unchanged files, 35x faster on re-run |
| `compress_photos.py` | Smart JPEG compression by resolution tier; PNG→JPEG conversion |
| `timeline_gaps.py` | Detect abnormal date gaps indicating missing photos |
| Unified `constants.py` | All format definitions consolidated; AVIF, WebM, MTS, ORF, RW2 added |

## v3.13 New Features — Rotation, Conversion & GPS

| Script | Trigger | What it does |
|--------|---------|-------------|
| `rotate_photos.py` | "rotate photo", "照片旋转", "方向纠正" | Batch-rotate photos to correct EXIF Orientation; applies pixel rotation, resets Orientation to 1, preserves EXIF; `--dry-run`, `--orientation N` filter, directory scan |
| `convert_format.py` | "convert format", "格式转换", "JPEG转WEBP" | JPEG/HEIC/PNG → WEBP/AVIF; preserves EXIF GPS/date/camera; 30-50% savings; `--quality N`, `--lossless`, `--keep-originals`, `--dry-run` with savings estimate |
| `fix_gps.py` | "fix gps", "GPS推断", "GPS缺失" | Infer missing GPS from temporally adjacent photos (±10 min); uses closest or averages; `--write-exif`, `--dry-run` |
| `is_animated_image()` | (internal) | Detect GIF/animated WebP/APNG; new `is_animated` DB column; scan reports animated count |
| `get_exif_orientation()` | (internal) | Extract EXIF Orientation (1-8); new `orientation` DB column; scan reports rotated count |
| `Image.MAX_IMAGE_PIXELS` | (internal) | Decompression bomb protection — 60MP limit, prevents OOM from malicious images |
| `AVIF_SUPPORT` | (internal) | AVIF decode support (Pillow ≥11 native or `pillow-avif-plugin`); new `AVIF_EXTS` in constants |

```bash
# Fix EXIF rotation (dry-run first)
python3 scripts/rotate_photos.py -i ./photo_index.db --dry-run
python3 scripts/rotate_photos.py -i ./photo_index.db

# Convert to WEBP (save 30-50% space)
python3 scripts/convert_format.py -i ./photo_index.db --to webp --dry-run
python3 scripts/convert_format.py -i ./photo_index.db --to webp --quality 85

# Infer missing GPS from neighbors
python3 scripts/fix_gps.py -i ./photo_index.db --dry-run
python3 scripts/fix_gps.py -i ./photo_index.db --write-exif
```

## v3.12 New Features — iCloud Optimization Handling

| Script | Trigger | What it does |
|--------|---------|-------------|
| `icloud_utils.py` | (internal module) | Shared iCloud detection: `.icloud` companion file, xattr, size heuristic; `brctl download` with polling; disk space check |
| `check_icloud.py` | "check icloud", "iCloud优化" | Scan directory for iCloud-only files, report count/size/estimates, **disk space check before download**, batch download with progress, `--max-download N` for limited space, `--min-free GB` safety buffer |
| `scan_photos.py --skip-icloud` | "skip icloud" | Skip iCloud placeholder files during scan |
| `scan_photos.py --download-icloud` | "download icloud" | Trigger `brctl download` for each placeholder, then scan full file |
| `--exclude-icloud` | (dedup flag) | `find_exact_duplicates.py` and `find_similar_photos.py` — skip unreliable placeholder hashes/pHashes |

```bash
# Step 1: Check what needs downloading (with disk space estimate)
python3 scripts/check_icloud.py -i ~/Pictures/Photos --report

# Step 2a: Download all (disk space checked first)
python3 scripts/check_icloud.py -i ~/Pictures/Photos --download

# Step 2b: Download in batches when disk space is limited
python3 scripts/check_icloud.py -i ~/Pictures/Photos --download --max-download 100
python3 scripts/check_icloud.py -i ~/Pictures/Photos --download --min-free 2  # reduce safety buffer

# Step 2c: Skip iCloud files entirely (metadata may be unreliable)
python3 scripts/scan_photos.py -i ~/Pictures/Photos -o index.db --skip-icloud

# Step 3: Scan (after download, or with --download-icloud for inline download)
python3 scripts/scan_photos.py -i ~/Pictures/Photos -o index.db --download-icloud

# Step 4: Dedup with iCloud exclusion
python3 scripts/find_exact_duplicates.py -i index.db -o dups.csv --exclude-icloud
python3 scripts/find_similar_photos.py -i index.db -o similar.csv --exclude-icloud
```

```bash
# Detect corrupted files
python3 scripts/detect_corrupted.py --index photo_index.db --report corrupted.csv

# Fix missing dates (dry-run first)
python3 scripts/fix_dates.py --index photo_index.db --dry-run
python3 scripts/fix_dates.py --index photo_index.db --write-exif --report fixed.csv

# Verify backup completeness
python3 scripts/verify_backup.py --source ~/Photos --backup /Volumes/Backup/Photos --full

# Find duplicate folders
python3 scripts/find_duplicate_folders.py --index photo_index.db

# Space what-if analysis
python3 scripts/library_stats.py --index photo_index.db --what-if

# Full pipeline with all v3.10 enhancements
python3 scripts/organize_photos.py --source ~/Pictures/Export \
  --assess-quality --detect-live-photos --detect-corrupted --fix-dates \
  --cluster-events --create-event-albums --strategy quality --dry-run
```

```bash
# Quality assessment → feeds into dedup scoring
python3 scripts/assess_quality.py --index photo_index.db

# Detect Live Photos → protects pairs during dedup
python3 scripts/detect_live_photos.py --index photo_index.db

# Interactive timeline
python3 scripts/generate_timeline.py --index photo_index.db --output timeline.html

# Event clustering (write event_id back to DB for timeline integration)
python3 scripts/cluster_events.py --index photo_index.db --output events.json --write-db

# Smart rename (dry-run first)
python3 scripts/rename_photos.py --index photo_index.db --template "{date}_{camera}_{seq}"

# GPX geotag
python3 scripts/gpx_geotag.py --index photo_index.db --gpx track.gpx --dry-run

# Video dedup
python3 scripts/find_similar_videos.py --index photo_index.db --output video_dupes.csv
```

## Interactive Review — Smart Dedup with Human Approval

Instead of blindly auto-deleting, use `generate_review.py` to review before any action:

```bash
# Generate interactive review page
python3 scripts/generate_review.py \
  --index photo_index.db \
  --duplicates duplicates_exact.csv \
  --similar duplicates_similar.csv \
  --output review.html
```

**Page features:**
- 📋 Shows album membership, date, camera, metadata score for each photo
- 🧠 Smart strategy rules (pick one, apply to all groups at once):
  - **保留元数据最全的** — highest EXIF/camera/GPS/date completeness score
  - **保留日期最早的** — keep the original, remove later copies
  - **保留日期最新的** — keep the final edit
  - **保留分辨率最高的** — keep the sharpest version
  - **保留指定相册的** — keep photos from your preferred album
- ⭐ Favorites are never auto-marked for deletion
- 📊 Real-time stats: reviewed count, marked-for-deletion count, reclaimable space
- 💾 Export decisions as CSV → feed to `apply_move_plan.py`

**Never deletes files directly** — the page only records your decisions.

## Reverse Geocoding — GPS → Place Names

Automatically converts GPS coordinates to city/region/country during scan. Uses 3 backends with auto-detection:

1. **CoreLocation** (macOS offline, fastest) — no API calls
2. **Locationator** (macOS HTTP API) — local network
3. **Nominatim** (online, always available) — OpenStreetMap API

```bash
# Scan with geocoding (default)
python3 scripts/scan_photos.py --source ~/Photos --output index.db

# Disable geocoding for faster scan
python3 scripts/scan_photos.py --source ~/Photos --output index.db --no-geocode

# Query a single coordinate
python3 scripts/reverse_geocode.py --lat 39.90 --lon 116.41
```

Persistent JSON cache (`geocode_cache.json`) avoids redundant API calls across runs.

## EXIF Editing — Modify Photo Metadata Safely

```bash
# Strip GPS data from indexed photos (dry-run first!)
python3 scripts/edit_exif.py strip-gps --index index.db --dry-run
python3 scripts/edit_exif.py strip-gps --index index.db

# Set EXIF date
python3 scripts/edit_exif.py set-date --date "2025-06-15T14:30:00" --paths photo.jpg

# Write tags/keywords
python3 scripts/edit_exif.py set-tags --tags "vacation,beach" --paths photo.jpg
```

Safety: `.bak` backup created before edit, restored on error, cleaned on success.

## Photos.app Album Organization — Create Albums by Date/Category

Create albums directly in Photos.app (not just file-system folders):

```bash
# Organize by year/month
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by date

# Organize by year only
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by year

# Organize by category (📸 Photos, 📱 Screenshots, 🔄 Burst, 💬 WeChat)
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by category

# Organize by format (JPEG, HEIC, PNG)
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by format

# Smart: year + category (e.g., "2026/📸 Photos", "2026/📱 Screenshots")
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by smart

# Preview without making changes
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by date --dry-run
```

| `--album-organize-by` | Album names | Best for |
|------------------------|-------------|----------|
| `date` | `2026/06 – June` | Timeline browsing |
| `year` | `2026` | Yearly overview |
| `category` | `📸 Photos`, `📱 Screenshots` | Quick filtering |
| `format` | `JPEG`, `HEIC` | Format management |
| `smart` | `2026/📸 Photos` | Combined timeline + category |

## HTML Report — Before/After Diff

After `--mode photos-album` or `--mode dedup`, an HTML report is automatically generated with:

- **Summary cards** — albums created, photos organized, errors
- **Before → After diff** — new albums, changed albums (photo count delta), unchanged albums
- **Library overview** — total photos, size, date range, format count
- **Category & format distribution** — bar charts
- **Album cards** — thumbnails, photo count, status badges (新建/已有/失败)

Report is saved to `{output_dir}/reports/album_report.html` and auto-opened in browser.

Works with `--dry-run` too — preview what *would* change before executing.

## Library Health & Insights — Read-Only Stats

Get an at-a-glance health report of any scanned library — **never modifies anything**:

```bash
# Terminal report (totals, category/format/year breakdown, health flags, top space hogs)
python3 scripts/library_stats.py --index photo_index.db

# Also write a self-contained HTML report
python3 scripts/library_stats.py -i photo_index.db --report health.html

# Machine-readable JSON (for piping into other tools)
python3 scripts/library_stats.py -i photo_index.db --format json

# Or via the orchestrator (scans first, then reports, auto-opens HTML)
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode stats
```

Surfaces: total items/size/date span · category & format & year distribution ·
health flags (screenshots, no-EXIF, GPS/privacy, iCloud-only, possibly-blurry
via Apple sharp score, favorites) · top-10 space consumers.

## Output Directory Structure

```
snaptidy_output/          # Default output (--output-dir)
├── scan/                 # Scan results
│   ├── photo_index.db    # SQLite metadata index
│   └── duplicates.csv    # Detected duplicate groups
├── plans/                # Move plans & manifests
│   ├── move_plan.csv     # Planned actions
│   └── plan_manifest.json
├── reports/              # HTML reports
│   ├── album_report.html # Album organization report
│   ├── library_health.html # Library health & insights (--mode stats)
│   └── preview.html      # Duplicate thumbnail preview
└── logs/                 # Execution logs
    └── move_log.csv      # Applied move log
```

## Shared Modules (internal)

Common logic lives in three importable modules (single source of truth — no duplication):

- `scripts/photo_metadata.py` — SHA-256, pHash, EXIF (datetime/GPS/camera/subsec/orientation), image size, aspect ratio, animated image detection, decompression bomb protection + optional-dependency flags (Pillow/piexif/imagehash/pillow-heif/pillow-avif)
- `scripts/constants.py` — extension sets, format-family mapping, Core Data epoch, month names, album-name maps, `format_size`
- `scripts/applescript_utils.py` — AppleScript string escaping + `osascript` invocation
- `scripts/rotate_photos.py` — Batch EXIF orientation fix (rotate pixels, reset Orientation to 1)
- `scripts/convert_format.py` — JPEG/HEIC/PNG → WEBP/AVIF conversion (preserve EXIF, save 30-50%)
- `scripts/fix_gps.py` — Infer missing GPS from temporally adjacent photos
- `scripts/icloud_utils.py` — iCloud detection (`.icloud` companion, xattr, size heuristic), `brctl download` with polling, disk space checking, batch download

## CLI Conventions

Flags are standardized across all scripts (old names kept as aliases):

- `--source` (`--input` / `--library`, `-i` for folders) — photo source
- `--index` (`-i`) — SQLite metadata index (consumed by dedup/report tools)
- `--output` (`-o`, also `--report` for HTML producers) — output path

## Photos.app "Recently Deleted" — Safe Cleanup

When using `--mode photos-trash`, deleted photos go to Photos.app's **"最近删除" / "Recently Deleted"** album (30-day recovery).

- **First use**: macOS will show an automation permission dialog — click "允许" / "Allow"
- **Permission denied?**: Go to 系统设置 > 隐私与安全性 > 自动化, enable Photos for your Terminal
- **Fallback**: If permission unavailable, a `.applescript` file is generated for manual execution

For detailed detection algorithms, priority rules, import workflow, iCloud integration, performance benchmarks, and troubleshooting, see `references/`.
