# AGENTS.md — SnapTidy Project Rules

This file provides universal AI coding rules for the SnapTidy project. Compatible with Claude Code, Cursor, GitHub Copilot, Windsurf, and other AI coding agents.

## Project Overview

SnapTidy is a macOS photo/video organizer AI skill. It scans photo libraries, detects duplicates (SHA-256 exact + pHash perceptual + scaled + cross-format + burst), generates safe move plans, provides HTML thumbnail previews, and supports undo. It never deletes files. Supports both file-system scanning and Photos.app library scanning. Interactive one-command workflow via `organize_photos.py`. Import from external drives/Android into Photos.app with automatic dedup via `import_to_photos.py`. Reverse geocoding (GPS→place names) with persistent cache. EXIF editing (strip GPS, set dates, write tags) with backup/restore safety.

## Code Conventions

- **Language**: Python 3.9+
- **Style**: PEP 8, 4-space indent, max line length 120
- **Scripts**: All scripts under `scripts/` are CLI tools using `argparse`
- **Input/Output**: SQLite (.db) or CSV (.csv) — SQLite preferred for 100k+ photos
- **Encoding**: All CSV files use UTF-8 with BOM for Excel compatibility
- **Zero data loss**: Scan scripts commit each entry immediately to SQLite (WAL mode + synchronous=NORMAL)

## Safety Constraints

- NEVER implement file deletion functionality
- NEVER modify files inside `.photoslibrary` or `.photolibrary` packages directly — use `scan_photos_library.py` (read-only) or `apply_move_plan.py --mode photos-trash` (PyObjC deletion)
- All file operations must be read-only by default
- Move operations require an explicit user confirmation step
- Always log operations to a CSV audit trail
- macOS Trash mode is the safest move option (recoverable via Finder)
- Photos.app PyObjC deletion keeps the library database consistent
- Fast/Safe path confirmation: 1-9 moves brief `[Y/n]`, 10+ moves require explicit `"yes"`
- Always inform user that `--undo` is available after a move operation

## Architecture

```
Pipeline: Scan → Dedup → Review → Plan → Apply → Undo
          (read)  (read)  (read)   (read)  (move)  (reverse)

Scan modes:
  scan_photos.py          — File-system scan (exported folders, external drives)
  scan_photos_library.py  — Photos.app library scan (reads Photos.sqlite)

Dedup modes:
  find_exact_duplicates.py  — SHA-256 exact match
  find_similar_photos.py    — pHash + scaled + cross-format + burst

Preview:
  generate_preview.py       — HTML thumbnail preview (KEEP/MOVE badges)
  generate_review.py        — Interactive review page with smart strategy rules
                             (album/date/metadata comparison, auto-pick, CSV export)

Plan:
  generate_move_plan.py     — Smart priority move plan generation

Apply:
  apply_move_plan.py        — Move/trash/photos-trash + undo support

Interactive:
  organize_photos.py        — One-command pipeline

Import:
  import_to_photos.py      — Import from external drive/Android → dedup against library → import

Geocode:
  reverse_geocode.py        — GPS → place names (CoreLocation/Locationator/Nominatim + persistent cache)

Quality:
  assess_quality.py          — Blur/brightness/contrast/quality score (Laplacian + pixel stats)

EXIF Edit:
  edit_exif.py              — Strip GPS / set dates / write tags (backup/restore safety)

Live Photo:
  detect_live_photos.py      — Identify HEIC+MOV pairs, keep together during dedup

Orphan RAW:
  find_orphan_raw.py         — Find RAW without JPEG companion (or vice versa)

Timeline:
  generate_timeline.py        — Interactive HTML timeline (year/month/day zoom + category filters)

Library Compare:
  compare_libraries.py        — Photos.app vs file-system (SHA-256 + filename matching)

Google Import:
  import_google_takeout.py    — Google Photos Takeout import + JSON metadata merge

GPX Geotag:
  gpx_geotag.py               — Assign GPS from GPX track files (timestamp interpolation)

Event Clustering:
  cluster_events.py           — Auto-group photos by time + location into events

Video Dedup:
  find_similar_videos.py      — Frame sampling + pHash for video duplicates

Smart Rename:
  rename_photos.py            — Rename by EXIF date/camera/location templates
```

Each step is independent and produces a .db/.csv for the next step. This design allows:

- Running any step independently
- Manual review between steps
- Re-running from any point without data loss
- SQLite storage for efficient large-library operations
- HTML preview for visual review before committing
- Streaming writes for zero data loss on crash

## Auto-Categorization Rules (15+ Languages)

Detection order matters (first match wins):
1. **burst**: `_HDR`, `_burst`, `连拍`, `連拍`, `버스트`, `연속`, `連写`, `バースト` — checked before screenshot
2. **screenshot**: English/中文/日本語/한국어/Русский/Français/Deutsch/Español/Italiano/Português/Nederlands/ไทย/Tiếng Việt/Bahasa + iOS `IMG_\d+.PNG`
3. **wechat**: `mmexport`, `wx_camera_`, `microMsg`, `微信`, `KakaoTalk`, `LINE_`
4. **video**: by file extension
5. **photo**: default

**IMPORTANT**: `IMG_` is NOT in screenshot patterns. iOS camera photos use `IMG_*.JPG`; only `IMG_*.PNG` are screenshots.

## Detection Methods

| Method | Key | Algorithm | Threshold |
|--------|-----|-----------|-----------|
| pHash | `exact_phash` / `fuzzy_phash` | Identical/similar perceptual hash | Hamming ≤ threshold |
| Scaled | `scaled` | Aspect ratio + dimension ratio + pHash verify | Hamming ≤ 10 |
| Cross-format | `cross_format` | Aspect ratio + same dims + format differs + pHash verify | Hamming ≤ 12 |
| Burst | `burst_subsec` | Same DateTimeOriginal + different SubSecTime | Exact second match |

## Interactive Workflow (organize_photos.py)

The interactive workflow collects user preferences and orchestrates the full pipeline:

1. **collect_preferences_interactive()** — prompts for: source type, organize mode, dedup method, strategy, preferred folder, trash mode
2. **run_scan()** — calls scan_photos or scan_photos_library based on source type
3. **run_detect()** — runs selected detection methods (exact + similar variants)
4. **show_preview()** — displays summary stats (total moves, by category, by match type, reclaimable space)
5. **generate_manifest()** — creates `plan_manifest.json` with preferences, summary, and all planned moves
6. **confirm_plan()** — Fast/Safe path model: 1-9 moves = brief `[Y/n]`, 10+ moves = require explicit `"yes"`
7. **apply_plan()** — executes moves with undo record saved automatically

### External Source Detection

- **check_icloud_status()** — checks for `.icloud` companion files and `com.apple.iCloud.syncState` xattr
- **download_icloud_file()** — triggers download via `brctl download`
- **detect_android_mount()** — scans `/Volumes/` for DCIM folders (Android, Galaxy, Pixel, etc.)
- **detect_external_drives()** — scans `/Volumes/` for photo-containing external drives

## Undo System (apply_move_plan.py)

- **save_undo_record()** — creates JSON in `undo_records/` subdir with source/destination/status + 30-day expiry
- **undo_last()** — reverses most recent operation in reverse order, removes undo file on success
- **compute_file_checksum()** — SHA-256 verification for moved files
- Trash operations cannot be undone from CLI — user must use Finder > Put Back

## HTML Preview (generate_preview.py)

- **get_thumbnail_base64()** — creates base64 JPEG thumbnail (200px max) embedded in HTML
- **generate_preview_html()** — produces standalone HTML page with:
  - Summary stats bar (total groups, images, match type breakdown)
  - Per-group cards: thumbnail, KEEP/MOVE badge, filename, dimensions, size, category, folder, EXIF, camera
  - Green border for KEEP, orange border for MOVE

## Folder Priority

Default scoring when quality is equal:
- DCIM/Photos/相册 → +25 (camera originals)
- Date folders (2024/, 2023/) → +10
- Backup/Downloads → -15
- WeChat/微信 → -10

Users can override with `--prefer-folder` flag (+50 bonus).

## Database Schema

SQLite `photos` table columns:
- Core: file_path (PK), filename, extension, size_bytes, sha256
- Time: exif_datetime, file_mtime, subsec_time
- Image: width, height, phash, aspect_ratio, format_family
- Classification: media_type, category, has_exif
- Location: gps_latitude, gps_longitude, place_city, place_region, place_country, place_country_code
- Camera: camera_make, camera_model
- Priority: folder_tag, scan_root, scanned_at
- Quality: blur_score, brightness, contrast, quality_score (from assess_quality.py)
- iCloud: icloud_state (from scan_photos.py — "local", "icloud_placeholder", "downloaded", "download_failed")
- v3.13: is_animated (INTEGER 0/1 — GIF/animated WebP/APNG), orientation (INTEGER 1-8 — EXIF Orientation)
- Photos.app exclusive: photos_favorite, photos_hidden, photos_screenshot, photos_duplicate_visibility, photos_cloud_state, photos_albums, photos_shared_albums, photos_icloud_locally_available

Schema migration: `ALTER TABLE ADD COLUMN` with try/except (backward compatible).

## Dependencies

- Pillow: Image reading and metadata
- piexif: EXIF data extraction (including SubSecTime) + EXIF editing (strip GPS, set dates, write tags)
- imagehash: Perceptual hash computation
- pillow-heif: Optional HEIC/HEIF image support
- numpy: Optional for fast blur detection (Laplacian variance). Falls back to PIL if unavailable.
- pyobjc-framework-Photos: Optional Photos.app PyObjC deletion
- photoscript: Optional high-level Photos.app import (recommended for import workflow)
- exiftool: Optional EXIF editing fallback for HEIC/RAW (via subprocess)

Do NOT add pandas, numpy, or other heavy dependencies unless absolutely necessary.

## Import Workflow (import_to_photos.py)

Import photos from external sources (hard drives, Android phones) into Photos.app with automatic dedup.

### Pipeline

```
Source Scan → SHA-256 Hash → Library Index (Photos.sqlite) → Dedup → Import → Report
```

### Import Methods (auto-selected by default)

| Method | Dependencies | Notes |
|--------|-------------|-------|
| photoscript | `pip install photoscript` | Most reliable, high-level API |
| osascript | None (macOS built-in) | No extra deps, slower per-file |
| ScriptingBridge | `pip install pyobjc` | Low-level PyObjC, medium speed |

### Key Functions

- **detect_external_sources()** — scans `/Volumes/` for Android DCIM and external drive photo folders
- **build_library_index()** — reads Photos.sqlite (copy, never original) → SHA-256 index for dedup
- **dedup_against_library()** — SHA-256 comparison of source files vs library
- **import_via_photoscript/osascript/scriptingbridge()** — imports unique files into Photos.app
- **get_shared_albums()** — reads shared album info from Photos.sqlite (Z_ENT=CloudSharedAlbum)
- **get_icloud_storage_info()** — checks available disk space for iCloud sync safety

### Shared Album Limitations

- **READ-ONLY**: AppleScript/ScriptingBridge cannot add photos to shared albums
- Workaround: import to regular album → manually drag to shared album in Photos.app
- Shared album detection: ZGENERICALBUM where Z_ENT = CloudSharedAlbum (from Z_PRIMARYKEY)
- iCloud Shared Photo Library (macOS Ventura+) uses ZSHARE table — also read-only

### iCloud Sync Awareness

- **ZCLOUDRESOURCE.ZISLOCALLYAVAILABLE** — determines if a photo is local or iCloud-only
- **ZASSET.ZCLOUDLOCALSTATE** — general cloud state flag
- Library index only includes locally-available files (iCloud-only skipped to avoid missing file errors)
- Storage check warns if < 5 GB available before import

### Checkpoint & Resume

- **--resume** flag enables resuming interrupted imports
- **import_checkpoint.json** stores state between runs
- **SIGINT/SIGTERM handler** saves checkpoint on Ctrl+C

## Reverse Geocoding (reverse_geocode.py)

Converts GPS coordinates to human-readable place names. 3 backends with auto-detection:

1. **CoreLocation** (macOS offline) — fastest, no network calls. Uses `CoreLocation` via `pyobjc` or `locationator` CLI.
2. **Locationator** (macOS HTTP API) — local network, no internet needed.
3. **Nominatim** (online) — OpenStreetMap API, always available. Rate-limited (1 req/s).

Persistent JSON cache (`geocode_cache.json`) alongside the output DB. Cache key: rounded lat/lon to 3 decimal places (~111m precision). Avoids redundant API calls across runs.

Scan integration: `scan_photos.py` and `scan_photos_library.py` call `reverse_geocode()` automatically when GPS data exists. Populates `place_city`, `place_region`, `place_country`, `place_country_code` columns. Use `--no-geocode` to disable.

## EXIF Editing (edit_exif.py)

Modify photo metadata with safety guarantees:

### Operations

| Operation | Description |
|-----------|-------------|
| `strip-gps` | Remove GPS data from indexed photos (with `--only-gps` flag) |
| `set-date` | Set EXIF capture date on specific files |
| `set-tags` | Write keywords/tags to photo EXIF |

### Safety Mechanisms

- **Backup/restore**: `.bak` files created before modification, cleaned on success, restored on error
- **`--dry-run`**: Preview changes without modifying files
- **`--no-backup`**: Skip backup creation (faster, less safe)
- **Format support**: piexif for JPEG/TIFF, exiftool fallback for HEIC/RAW

### Batch Operations

`strip-gps --index` reads the scan index DB and strips GPS from all indexed photos. Use `--only-gps` to only process photos that have GPS coordinates.

## Quality Assessment (assess_quality.py)

Compute blur/brightness/contrast/quality metrics for each image. Results stored in DB columns: `blur_score`, `brightness`, `contrast`, `quality_score`.

### Quality Score Formula (0-100)

| Component | Weight | Method |
|-----------|--------|--------|
| Sharpness | 40% | Laplacian variance (numpy or PIL fallback) |
| Exposure | 25% | Mean brightness — penalize too dark (<60) or clipped (>180) |
| Contrast | 20% | Pixel intensity standard deviation |
| Resolution | 15% | Pixel count mapping (1MP→6, 8MP→10, 20MP→15) |

### Integration

- `generate_move_plan.py --strategy quality` considers blur penalty and quality_score bonus
- `generate_review.py` shows quality badge (Q0-100) on review cards, adds "保留画质最好的" strategy
- `organize_photos.py --assess-quality` runs quality assessment after scan
- Use `--incremental` to only assess photos without existing scores

## Live Photo Protection

`detect_live_photos.py` writes `live_photo_group` column. `generate_move_plan.py` reads this column:

- **Keep protection**: If the kept file is part of a Live Photo pair, its partner is never moved
- **Carry along**: If a Live Photo component is moved, its partner is moved to the same destination
- **organize_photos.py --detect-live-photos** enables Live Photo detection before dedup

## Event Clustering + Timeline Integration

`cluster_events.py --write-db` writes `event_id` column. `generate_timeline.py` reads this column:

- **Event banners**: Purple gradient banners within each year showing event name, dates, photo count
- **Event tags**: Colored tags on individual photo thumbnails showing event assignment
- **Event filter**: Dropdown to filter timeline by specific event
- **organize_photos.py --cluster-events** runs clustering and writes event_id to DB

## v3.9 Enhancement Flags (organize_photos.py)

All v3.9 features are available as enhancement flags that run after scan but before dedup/organize:

| Flag | Script | Effect |
|------|--------|--------|
| `--assess-quality` | assess_quality.py | Compute blur/brightness/contrast scores |
| `--detect-live-photos` | detect_live_photos.py | Identify HEIC+MOV pairs |
| `--generate-timeline` | generate_timeline.py | Interactive HTML timeline |
| `--cluster-events` | cluster_events.py | Auto-group photos into events |
| `--cluster-gap N` | cluster_events.py | Event gap in hours (default: 4) |
| `--find-orphan-raw` | find_orphan_raw.py | Find RAW without JPEG companion |
| `--find-similar-videos` | find_similar_videos.py | Video dedup via frame sampling |
| `--smart-rename` | rename_photos.py | Rename by EXIF template (dry-run) |
| `--rename-template T` | rename_photos.py | Template string (default: {date}_{camera}_{seq}) |

## v3.10 New Features

### Corrupted File Detection (detect_corrupted.py)

Layered integrity check for images and videos:
1. **0-byte/missing check** — instant
2. **Pillow verify()** — structural check (fast, ~100x faster than load)
3. **Pillow load()** — full decode (catches truncated images that pass verify)
4. **ffmpeg probe** — video playability check (30s timeout per file)

DB columns: `is_corrupted` (INTEGER), `corruption_type` (TEXT), `corruption_detail` (TEXT)

ThreadPoolExecutor for parallel processing. `--incremental` skips already-verified files.

### Photo Date Correction (fix_dates.py)

Three strategies for fixing missing/wrong EXIF dates:
1. **Filename extraction** — 15+ regex patterns (iOS IMG_, Android Screenshot_, WeChat WX/mmexport/microMsg, WhatsApp IMG-...-WA, Facebook FB_IMG, Signal, LINE, KakaoTalk, Unix timestamps, generic YYYYMMDD_HHMMSS)
2. **Neighbor inference** — photos in same folder with valid dates, sorted by filename order
3. **File mtime fallback** — last resort when no other source available

Writes to EXIF DateTimeOriginal and DateTimeDigitized via piexif (JPEG/TIFF) or exiftool (HEIC/RAW).

`--strategy` flag: `all` (default), `filename-only`, `neighbors`, `mtime`

### Backup Verification (verify_backup.py)

Quick mode (filename + size matching) vs Full mode (SHA-256 hash matching, catches renames).

Can use existing index DB or scan directories on-the-fly. Reports: missing files, extra files, changed files, coverage percentage.

### Duplicate Folder Detection (find_duplicate_folders.py)

Builds folder → file hash set mapping, computes Jaccard similarity between folder pairs. Optimized with reverse hash index to only compare folders sharing at least one file. Union-find groups near-duplicate folders (≥90% similarity).

### Space What-If Analysis (library_stats.py --what-if)

Categories: screenshots, duplicates, RAW files, low quality (quality_score < 30), videos, no-date, corrupted, with-GPS (privacy). Shows file count + bytes + percentage for each category.

### v3.10 Enhancement Flags (organize_photos.py)

| Flag | Script | Effect |
|------|--------|--------|
| `--detect-corrupted` | detect_corrupted.py | Find broken/truncated images and unplayable videos |
| `--fix-dates` | fix_dates.py | Fix missing EXIF dates |
| `--fix-dates-strategy` | fix_dates.py | Strategy: all/filename-only/neighbors/mtime |
| `--create-event-albums` | organize_photos.py | Create Photos.app albums from events |
| `--verify-backup DIR` | verify_backup.py | Verify backup against directory |
| `--find-duplicate-folders` | find_duplicate_folders.py | Find duplicate/similar folders |

## v3.11 — Performance & New Tools

### Parallel Scanning (scan_photos.py --parallel N)

ThreadPoolExecutor with batch commits (every 50 entries). 2.9x speedup on 4 threads. Results identical to serial mode.

### Incremental Scanning (scan_photos.py --incremental)

Compares (file_path, size_bytes, file_mtime) against existing DB entries. Only processes new or modified files. 35x faster on re-run (0.1s vs 3.4s for 270 files).

### pHash Prefix-Index Optimization

Groups phashes by first N hex chars, only compares within same/adjacent prefix groups. Reduces O(n²) to ~5% comparisons for typical thresholds (≤10).

### Photo Compression (compress_photos.py)

Resolution-based JPEG quality tiers: >8MP→85, 2-8MP→90, <2MP→95. PNG→JPEG conversion (skips transparent). Minimum savings threshold (>90% original = skip). `--dry-run`, `--backup .orig`, `--report CSV`.

### Timeline Gap Detection (timeline_gaps.py)

Adaptive threshold (median + 3*IQR) or fixed `--min-gap-days`. Severity: critical/major/moderate/minor. Monthly heatmap + estimated missing photo count.

## v3.12 — iCloud Optimization Handling

### Problem

macOS "Optimize Storage" offloads original photos to iCloud, keeping only small thumbnails (2-50 KB) locally. These thumbnails have different SHA-256 hashes and pHashes than originals, causing false results in dedup.

### Detection (`icloud_utils.py`)

Three methods checked for each file:
1. **`.icloud` companion file** — iCloud Drive style: `.{filename}.icloud` exists next to missing original
2. **Extended attribute** — `com.apple.iCloud.syncState` xattr on the file
3. **Size heuristic** — HEIC < 100 KB or JPEG < 20 KB = likely thumbnail

### Three Scan Modes (`scan_photos.py`)

| Mode | Flag | Behavior | DB `icloud_state` value |
|------|------|----------|--------------------------|
| Warn (default) | `--warn-icloud` | Scan but mark as placeholder | `icloud_placeholder` |
| Skip | `--skip-icloud` | Skip entirely, don't index | (not in DB) |
| Download | `--download-icloud` | Trigger `brctl download`, wait, re-scan | `downloaded` or `download_failed` |

### Standalone Check Script (`check_icloud.py`)

```bash
# Report: count, size, estimates, disk space check
python3 check_icloud.py -i ~/Pictures/Photos --report

# Download all (with disk space safety check)
python3 check_icloud.py -i ~/Pictures/Photos --download

# Download in batches when disk space is limited
python3 check_icloud.py -i ~/Pictures/Photos --download --max-download 100

# Reduce safety buffer (default: 5 GB)
python3 check_icloud.py -i ~/Pictures/Photos --download --min-free 2

# Force download despite space warning (not recommended)
python3 check_icloud.py -i ~/Pictures/Photos --download --force
```

### Disk Space Safety

Before downloading, the script:
1. Estimates download size (thumbnail size × 25 multiplier)
2. Checks available disk space via `shutil.disk_usage()`
3. Subtracts safety buffer (default 5 GB, configurable via `--min-free`)
4. If insufficient: reports shortfall, suggests `--max-download N`, `--skip-icloud`, or space cleanup
5. During download: checks disk space after each file, stops if below buffer

### Downstream Filtering

| Script | Flag | Effect |
|--------|------|--------|
| `find_exact_duplicates.py` | `--exclude-icloud` | Excludes `icloud_state IN ('icloud_placeholder', 'download_failed')` from SHA-256 dedup |
| `find_similar_photos.py` | `--exclude-icloud` | Excludes from pHash, scaled, cross-format, and detect-all modes |
| `library_stats.py` | (automatic) | Shows `icloud_placeholder`, `icloud_downloaded`, `icloud_failed` counts in health flags |

## v3.13 — Rotation, Conversion & GPS

### Batch EXIF Rotation (rotate_photos.py)

Fix photos with incorrect EXIF Orientation tags. Many cameras (especially iPhones) store portrait images sideways with Orientation=6. This script physically rotates pixels and resets Orientation to 1.

```bash
# Dry-run: preview which images need rotation
python3 rotate_photos.py -i ./photo_index.db --dry-run

# Apply rotation (updates DB orientation column too)
python3 rotate_photos.py -i ./photo_index.db

# Only fix specific orientation (e.g. 6 = portrait 90°)
python3 rotate_photos.py -i ./photo_index.db --orientation 6

# Scan directory without prior index
python3 rotate_photos.py -s /path/to/photos --dry-run
```

### Format Conversion (convert_format.py)

Convert JPEG/HEIC/PNG to WEBP (30% savings) or AVIF (50% savings). Preserves EXIF metadata and file mtime.

```bash
# Dry-run: preview space savings
python3 convert_format.py -i ./photo_index.db --to webp --dry-run

# Convert to WEBP (quality 85, delete originals)
python3 convert_format.py -i ./photo_index.db --to webp --quality 85

# Convert only large files to AVIF, keep originals
python3 convert_format.py -s /path/to/photos --to avif --min-size 500 --keep-originals

# Lossless conversion
python3 convert_format.py -i ./photo_index.db --to webp --lossless
```

### GPS Neighbor Inference (fix_gps.py)

Infer missing GPS coordinates from photos taken within ±10 minutes. Uses closest reference or averages multiple. Supports `--write-exif` to write to image files.

```bash
# Dry-run: preview inferred GPS
python3 fix_gps.py -i ./photo_index.db --dry-run

# Write inferred GPS to DB
python3 fix_gps.py -i ./photo_index.db

# Also write to EXIF in the image files
python3 fix_gps.py -i ./photo_index.db --write-exif

# Use wider time window (30 minutes)
python3 fix_gps.py -i ./photo_index.db --window 30
```

### New DB Columns

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `is_animated` | INTEGER | 0 | 1 if GIF/animated WebP/APNG |
| `orientation` | INTEGER | 1 | EXIF Orientation (1-8), 1 = normal |

### Scan Output

`scan_photos.py` now reports:
- `🎬 N animated images detected (GIF/animated WebP/APNG)`
- `🔄 N images with EXIF orientation tag (use rotate_photos.py to fix)`
- `⚠️ N AVIF files found — install pillow-avif-plugin for full support`

### Decompression Bomb Protection

`Image.MAX_IMAGE_PIXELS` set to 60,000,000 (60 megapixels) in `photo_metadata.py`. Prevents OOM from maliciously crafted oversized image files. Images exceeding this limit will raise `DecompressionBombError`.

### AVIF Support

`AVIF_SUPPORT` flag in `photo_metadata.py` — tests native Pillow AVIF (≥11) then falls back to `pillow-avif-plugin`. New `AVIF_EXTS = {"avif"}` in `constants.py`. Scan warns about AVIF files if support is missing.
