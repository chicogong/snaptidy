# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.14.1] - 2026-06-18

### Changed

- **SKILL.md restored and expanded** — Codex's rewrite dropped 7 scripts
  from the intent routing table; all restored: `generate_review.py`,
  `detect_bad_extensions.py`, `detect_corrupted.py`, `library_stats.py`,
  `generate_timeline.py`, `compress_photos.py`, `verify_backup.py`,
  `detect_privacy_risks.py`, `rename_photos.py`. Strategy table
  (`quality`/`oldest`/`newest`/`folder`) restored as inline note.
  `license: MIT` added to frontmatter per agentskills.io spec.

- **Contract test relaxed** — `test_frontmatter_is_portable` now allows
  optional fields (`license`, `compatibility`, `allowed-tools`, `metadata`)
  per the agentskills.io specification, instead of hard-enforcing only
  `name` + `description`.

- **Safety-first rewrite** — Codex rewrote `references/safety.md` with
  non-negotiable rules, operation classes (read-only / reversible writes /
  special recovery), confirmation thresholds, and source-specific checks.
  Correctly distinguishes 3 recovery mechanisms: normal move `--undo`
  (30-day JSON record), macOS Trash (Finder > Put Back), Photos.app
  (Recently Deleted).

- **Intent routing table** — Codex added a routing table mapping user
  intents to starting scripts and reference docs.

- **Contract test suite** — new `scripts/test_skill_contract.py` with 8
  tests validating frontmatter portability, core conciseness, safety
  invariants, local link resolution, documented scripts existence,
  release version consistency, OpenAI adapter format, and CLI help.

- **OpenAI adapter** — new `agents/openai.yaml` for cross-agent
  portability.

- **clawhub.yaml synced** — version 3.3.0 → 3.14.0, description and tags
  updated to reflect v3.14 features.

- **README safety corrections** — default mode changed from `trash` to
  `move` (safer), undo scope clarified (normal moves only, not Trash),
  Photos.app trash mode added to safety table.

- **CI integration** — contract test added to `.github/workflows/ci.yml`
  before integration tests.

### Removed

- `docs/superpowers/` — Codex's internal design/plan documents, not
  needed in the published repository.

## [3.14.0] - 2026-06-18

### Added

- **Bad extension detection** — new `detect_bad_extensions.py` script:
  Reads file magic bytes and compares against declared extension. Detects
  files whose content doesn't match their extension (e.g., JPEG content
  with `.png` extension). Supports 20+ format signatures including JPEG,
  PNG, GIF, BMP, TIFF, WebP, HEIC/HEIF, AVIF, MP4/MOV, MKV, WMV, FLV,
  and RAW formats (CR2, ORF, RW2, RAF). Adds `bad_extension`,
  `actual_format`, `declared_format` DB columns. Parallel processing
  and incremental mode supported.

- **Multi-dimensional quality scoring** — `assess_quality.py` enhanced
  from 3 dimensions (blur/brightness/contrast) to 7 dimensions:
  1. Sharpness (Laplacian variance, 0-100)
  2. Exposure (brightness mapping, 0-100)
  3. Contrast (pixel intensity stddev, 0-100)
  4. Resolution (megapixel mapping, 0-100)
  5. Format quality (RAW > HEIC > AVIF > JPEG > PNG > BMP, 0-100)
  6. File size efficiency (bytes-per-pixel analysis, 0-100)
  7. EXIF completeness (date + GPS + camera presence, 0-100)
  Composite `quality_score` uses weighted formula across all 7 dimensions.
  New DB columns: `sharpness_score`, `exposure_score`, `contrast_score`,
  `resolution_score`, `format_score`, `filesize_score`, `exif_score`.

### Changed

- **SKILL.md drastically simplified** — reduced from 436 lines to 91 lines.
  Detailed feature tables moved to `references/features.md`. Description
  shortened from 1500+ chars to 3 sentences. Version updated to 3.14.0.

- **README badges and step numbering** — version badge 3.13 → 3.13.1,
  website badge text snaptidy.app → realtime-ai.chat, duplicate Step 1b
  labels fixed to 1b/1c/1d, landing page Quick Start command fixed.

- **CI workflow added** — `.github/workflows/ci.yml` with py_compile on
  all 42 scripts and v3.13 integration tests on every PR/push to main.

- **Older changelogs collapsed** — v3.8-v3.11 What's New sections wrapped
  in `<details>` tags in both READMEs for readability.

- **Dark mode for all HTML reports** — all 5 generated HTML pages
  (review, preview, timeline, album report, health report) now support
  `prefers-color-scheme: dark` with automatic theme switching.

- **Responsive design** — review, preview, and health report pages now
  include mobile breakpoints (@media 768px/480px) for tablet/phone use.

- **Keyboard shortcuts in review page** — arrow keys navigate groups,
  K applies smart strategy, R marks all remove, A marks all keep,
  1/2/3 switches tabs, E exports CSV.

- **UI language unified to Chinese** — preview page and timeline
  controls were English; now consistent with other pages.

- **Landing page updated** — version badge 30+ scripts → 42, added
  7-dimension quality and bad extension detection to feature cards
  and comparison table, JSON-LD feature list updated.

## [3.13.1] - 2026-06-17

### Fixed

- **Integration gap: animated image filtering** — v3.13 added
  `is_animated_image()` to `photo_metadata.py` but 8 downstream scripts
  were not updated to use it. This release propagates animated-image
  awareness to all affected scripts:
  - `find_similar_photos.py` — animated GIFs/WebP now excluded from
    pHash matching (unreliable hash for multi-frame images) in
    `group_by_phash_db()`, `detect_scaled_duplicates_db()`, and
    `detect_cross_format_duplicates_db()`
  - `compress_photos.py` — animated images now skipped (compressing
    GIF/animated WebP loses frames); two-tier check: DB column first,
    then on-disk verification; also fixed pre-existing bug where
    `extension` with leading dot never matched `IMAGE_EXTS` (which
    stores dotless extensions)
  - `convert_format.py` — animated images now skipped before
    conversion (format conversion would lose animation frames); new
    `skipped_animated` counter and report column
  - `detect_corrupted.py` — AVIF magic number check added to
    `_check_magic_number()` fallback (validates `ftyp` box contains
    `avif` or `avis` brand at bytes 4-12)
  - `library_stats.py` — new health flags: `animated` count and
    `rotated` count (EXIF orientation > 1); terminal output and
    HTML report cards updated
  - `generate_review.py` — `is_animated` and `orientation` fields
    added to all three item-building sections (duplicate groups,
    similar groups, standalone items); HTML badge rendering with
    animated (🎬) and rotation (🔄) indicators
  - `scan_photos_library.py` — `is_animated` and `orientation`
    columns added to schema migration list; values computed during
    scan via `is_animated_image()` and `get_exif_orientation()`
- `test_v313_integration.py` — new integration test suite (6 tests)
  verifying all downstream integrations work correctly

## [3.13.0] - 2026-06-18

### Added

- **AVIF format support** — `photo_metadata.py` now detects and registers
  AVIF decode support (native Pillow ≥11 or `pillow-avif-plugin`); new
  `AVIF_EXTS` / `AVIF_EXTENSIONS` in `constants.py`; scan reports
  unconverted AVIF files with install hint
- **Decompression bomb protection** — `Image.MAX_IMAGE_PIXELS` set to
  60 megapixels in `photo_metadata.py`, prevents OOM from malicious
  crafted image files
- **Animated image detection** — `is_animated_image()` in
  `photo_metadata.py` detects GIF / animated WebP / APNG; new
  `is_animated` column in DB (INTEGER 0/1); scan reports animated count
- **EXIF orientation detection** — `get_exif_orientation()` extracts
  EXIF Orientation (1-8); new `orientation` column in DB (INTEGER);
  scan reports rotated image count
- **`rotate_photos.py`** — batch-rotate photos to correct EXIF
  orientation: applies pixel rotation, resets Orientation to 1,
  preserves EXIF metadata; supports `--dry-run`, `--orientation N`
  filter, directory scan mode, CSV report, index DB update
- **`convert_format.py`** — batch convert JPEG/HEIC/PNG → WEBP/AVIF:
  preserves EXIF GPS/date/camera metadata, preserves file mtime,
  configurable quality (1-100) and lossless mode, `--min-size KB`
  filter, `--keep-originals`, `--dry-run` with space savings estimate,
  CSV report
- **`fix_gps.py`** — infer missing GPS from temporally adjacent photos:
  finds photos taken within ±N minutes (default 10, max 60) of a
  GPS-bearing photo, uses closest reference or averages multiple;
  `--dry-run`, `--write-exif`, `--window N`, CSV report; 100%
  inference rate in test burst scenario

### Changed

- `scan_photos.py` — new `is_animated` and `orientation` DB columns
  with migration; scan summary now reports animated images count and
  images with EXIF orientation tag; imports `is_animated_image` and
  `get_exif_orientation` from `photo_metadata`
- `constants.py` — new `AVIF_EXTS = {"avif"}` and
  `AVIF_EXTENSIONS = {".avif"}`; `missing_dependencies()` now reports
  `pillow-avif-plugin` when AVIF support is missing
- `photo_metadata.py` — `AVIF_SUPPORT` flag (tests native Pillow AVIF
  then falls back to `pillow-avif-plugin`); new functions:
  `is_animated_image()`, `get_exif_orientation()`,
  `apply_exif_orientation()`

## [3.12.0] - 2026-06-18

### Added

- **iCloud Optimization Handling** — when macOS "Optimize Storage" offloads
  original photos to iCloud (keeping only 2-50 KB thumbnails locally),
  SnapTidy now detects, skips, or downloads these placeholder files:
  - **`icloud_utils.py`** — shared module with `check_icloud_status()`
    (three detection methods: `.icloud` companion file, xattr, size
    heuristic), `download_icloud_file()` (brctl download + polling),
    `get_disk_space()`, `check_disk_space()`, `estimate_download_size()`,
    `batch_download()`, `scan_directory_for_icloud()`
  - **`check_icloud.py`** — standalone script: scan directory for
    iCloud-only files, report count/size/estimates, **disk space check
    before download with shortfall calculation**, batch download with
    progress, `--max-download N` for limited space, `--min-free GB`
    safety buffer, `--batch-size N` for periodic space checks,
    `--force` to override space warning, `--dry-run`
  - **`scan_photos.py`** — three iCloud modes: `--warn-icloud`
    (default, scan but mark), `--skip-icloud` (skip placeholders),
    `--download-icloud` (trigger brctl download then scan full file);
    new `icloud_state` DB column with index; iCloud statistics
    printed at end of scan
- **Downstream iCloud filtering**: `find_exact_duplicates.py
  --exclude-icloud` and `find_similar_photos.py --exclude-icloud`
  skip files with `icloud_state IN ('icloud_placeholder',
  'download_failed')` — their SHA-256/pHash values are unreliable

### Changed

- `library_stats.py` — health flags now include `icloud_placeholder`,
  `icloud_downloaded`, `icloud_failed` counts in terminal and HTML reports
- `organize_photos.py` — imports iCloud functions from shared
  `icloud_utils.py` module (removed duplicated inline functions)
- DB schema: new `icloud_state TEXT DEFAULT 'local'` column with index

### Disk Space Safety

When downloading iCloud files, the script:
1. Estimates download size (thumbnail size × 25 multiplier)
2. Checks available disk space via `shutil.disk_usage()`
3. Subtracts safety buffer (default 5 GB, `--min-free` configurable)
4. If insufficient: reports shortfall, suggests `--max-download N`,
   `--skip-icloud`, or space cleanup
5. During download: checks disk space after each file, stops if below buffer

## [3.11.0] - 2026-06-17

### Added

- **Parallel scanning** (`scan_photos.py --parallel N`) —
  ThreadPoolExecutor with batch commits, 2.9x speedup on 4 threads
- **Incremental scanning** (`scan_photos.py --incremental`) —
  skip unchanged files, 35x faster on re-run (0.1s vs 3.4s)
- **pHash prefix-index optimization** — groups by hex prefix, only
  compares within same/adjacent groups, reduces O(n²) to ~5%
- **Photo compression** (`compress_photos.py`) — resolution-based
  JPEG quality tiers, PNG→JPEG conversion, dry-run, backup safety
- **Timeline gap detection** (`timeline_gaps.py`) — abnormal date
  gaps with adaptive threshold, severity classification, heatmap

### Changed

- **Unified `constants.py`** — all format sets consolidated; added
  AVIF, WebM, MTS, ORF, RW2, RAF, SRW, RAW; dot-prefixed variants
  for direct suffix comparison; `JPEG_EXTS`, `HEIC_EXTS`, `MEDIA_EXTS`

## [3.10.0] - 2026-06-17

### Added

- **Corrupted image/video detection** (`detect_corrupted.py`) — find broken,
  truncated, 0-byte images and unplayable videos using layered Pillow
  verify+load and ffmpeg probe; parallel processing; writes `is_corrupted`,
  `corruption_type`, `corruption_detail` to DB
- **Photo date correction** (`fix_dates.py`) — fix missing/wrong EXIF dates
  by inferring from filename patterns (15+ patterns including iOS, Android,
  WeChat, WhatsApp, Signal, KakaoTalk, LINE), neighbor photos in same folder,
  and file mtime fallback; `--dry-run`, `--write-exif`, `--strategy` flags
- **Backup verification** (`verify_backup.py`) — verify photo backup
  completeness; quick mode (filename+size) and full mode (SHA-256, catches
  renames); reports missing/extra/changed files with coverage percentage
- **Duplicate folder detection** (`find_duplicate_folders.py`) — find folders
  that are complete or near-complete duplicates; Jaccard similarity;
  content-hash-based grouping; union-find for near-duplicate clusters (≥90%)
- **Space what-if analysis** (`library_stats.py --what-if`) — calculate space
  savings by category: "if I delete all screenshots/duplicates/RAW/low-quality/
  videos/corrupted files, how much space would I save?"
- **Event album auto-creation** (`organize_photos.py --create-event-albums`) —
  create Photos.app albums from `cluster_events.py` event groups

### Integration

- `organize_photos.py` gains `--detect-corrupted`, `--fix-dates`,
  `--fix-dates-strategy`, `--create-event-albums`, `--verify-backup`,
  `--find-duplicate-folders` flags
- `fix_dates.py` supports ISO 8601 date format with T separator
  (from Photos.app library scans)

## [3.9.0] - 2026-06-17

### Added
- **Quality assessment** (`assess_quality.py`) — Compute blur (Laplacian variance),
  brightness (mean pixel intensity), contrast (standard deviation), and composite
  quality score (0-100) for each image. Results stored in DB columns `blur_score`,
  `brightness`, `contrast`, `quality_score`. Integrated with `generate_move_plan.py`
  (blur penalty + quality bonus for `--strategy quality`) and `generate_review.py`
  (quality badge + "Keep best quality" strategy). Supports `--incremental` mode.
  Numpy for fast computation, PIL fallback without numpy.
- **Live Photo detection** (`detect_live_photos.py`) — Identify iPhone Live Photo
  pairs (HEIC+MOV with matching base filename in same directory). Writes
  `live_photo_group` column to DB so dedup tools keep pairs together.
- **Orphan RAW cleanup** (`find_orphan_raw.py`) — Find RAW files without a JPEG
  companion in the same directory (or vice versa with `--both`). Useful for
  photographers who shoot RAW+JPEG and want to clean up orphans.
- **Timeline viewer** (`generate_timeline.py`) — Interactive HTML page with
  zoomable year → month → day timeline, category filters (photo/screenshot/wechat/
  burst/video), quality badges, and responsive layout. Standalone HTML, no server.
- **Library comparison** (`compare_libraries.py`) — Compare Photos.app library
  against file-system folder by SHA-256 hash (definitive) and filename (approximate).
  Find photos only in library, only on disk, or shared between both.
- **Google Takeout import** (`import_google_takeout.py`) — Scan Google Photos
  Takeout exports, find JSON sidecar metadata files, merge date/GPS/description
  into photo EXIF. Optionally import into Photos.app. Handles Google's various
  sidecar naming conventions.
- **GPX geotagging** (`gpx_geotag.py`) — Assign GPS coordinates to photos without
  location data by matching EXIF timestamps against GPX track points. Uses linear
  interpolation between adjacent trackpoints. Supports `--tolerance`,
  `--timezone-offset`, `--write-exif`, and `--dry-run`.
- **Event clustering** (`cluster_events.py`) — Auto-group photos into events
  by time gap (default 4h) and optionally by location (city changes start new event).
  Generates event names like "Beijing (2025-06-15)". Can write `event_id` back to DB.
- **Video dedup** (`find_similar_videos.py`) — Find duplicate/similar videos
  using frame sampling (ffmpeg) + perceptual hash comparison. Supports configurable
  frame count, similarity threshold, and Hamming distance. Requires ffmpeg.
- **Smart rename** (`rename_photos.py`) — Rename photos using configurable templates
  with metadata tokens: `{date}`, `{time}`, `{camera}`, `{city}`, `{seq}`, `{original}`.
  Dry-run by default, collision-safe, undo record on execute.
- **"Keep best quality" strategy** in `generate_review.py` — New smart strategy
  option that selects the photo with the highest `quality_score` to keep.
- **Quality score integration** in `generate_move_plan.py` — `--strategy quality`
  now considers blur penalty and quality_score bonus when scoring duplicates.
- **Live Photo protection** in `generate_move_plan.py` — Reads `live_photo_group`
  column to keep Live Photo pairs together: if one component is kept, its partner
  is never moved; if one is moved, its partner is carried along.
- **Event clustering in timeline** (`generate_timeline.py`) — Reads `event_id` from
  DB (written by `cluster_events.py --write-db`) and shows event banners, colored
  event tags on thumbnails, and event filter dropdown.
- **v3.9 enhancement flags** in `organize_photos.py` — New flags: `--assess-quality`,
  `--detect-live-photos`, `--generate-timeline`, `--cluster-events`, `--cluster-gap`,
  `--find-orphan-raw`, `--find-similar-videos`, `--smart-rename`, `--rename-template`.
  All run after scan, before dedup/organize.
- **SKILL.md updated** to v3.9.0 with all 10 new scripts, triggers, and usage examples.

## [3.8.0] - 2026-06-16

### Added
- **Reverse geocoding** (`reverse_geocode.py`) — Convert GPS coordinates to place names
  (city/region/country) with 3 backends: CoreLocation (macOS offline, fastest),
  Locationator (macOS HTTP API), Nominatim (online, always available). Auto-detects
  best backend. Persistent JSON cache with 3-decimal-place rounding (~111m precision)
  alongside the output DB.
- **EXIF editing** (`edit_exif.py`) — Modify photo metadata with 3 operations:
  `strip-gps` (remove GPS data from indexed photos), `set-date` (set EXIF capture date),
  `set-tags` (write keywords/tags). Uses piexif for JPEG/TIFF with exiftool fallback
  for HEIC/RAW. Backup/restore safety: `.bak` files created before modification, cleaned
  on success, restored on error. `--dry-run` and `--no-backup` flags.
- **By-location organization** — `organize_photos.py --mode by-location` organizes photos
  into `Country/Region/City/filename` folder structure using reverse-geocoded place names.
  Falls back to GPS coordinate zones (1-degree grid ≈ 111km) when no place data available.
- **Location stats in library health** — `library_stats.py` now includes `by_location`
  breakdown showing top cities by photo count. Terminal output shows top 15 cities;
  HTML report includes a dedicated `📍 地点分布` section with purple color theme.
- **Geocode integration in scan** — `scan_photos.py` and `scan_photos_library.py` now
  perform reverse geocoding by default, populating `place_city`, `place_region`,
  `place_country`, `place_country_code` columns. Use `--no-geocode` to disable.
  Geocode cache initialized at scan start, flushed at scan end.
- **SQLite schema migration** — New columns added via `ALTER TABLE ADD COLUMN`
  (backward compatible): `place_city`, `place_region`, `place_country`,
  `place_country_code`. New indexes: `idx_place_city`, `idx_place_country`.

### Changed
- `organize_photos.py` `by-location` mode was previously a stub — now fully functional.
- `scan_photos.py` and `scan_photos_library.py` signatures changed: added
  `geocode: bool = True` parameter.

## [3.7.0] - 2026-06-17

### Added
- **Library health & insights** (`library_stats.py`) — read-only report with
  totals, category/format/year breakdowns, health flags (screenshots, no-EXIF,
  GPS/privacy, iCloud-only, possibly-blurry, favorites) and top space consumers.
  Three outputs: terminal, `--format json`, `--report` HTML. Also wired as
  `organize_photos.py --mode stats`.
- HTML before/after diff report for `--mode photos-album` (new/changed/unchanged
  albums with photo-count deltas), works under `--dry-run` too.
- Organized output directory structure: `scan/`, `plans/`, `reports/`, `logs/`.

### Changed
- **Refactor: extracted shared modules** eliminating ~600 lines of duplication —
  `photo_metadata.py` (hashing/EXIF/pHash/size), `constants.py`
  (extensions/format-family/epoch/month-names/album-maps/`format_size`),
  `applescript_utils.py` (escaping + osascript).
- **Standardized CLI flags** across all scripts (backward-compatible aliases):
  `--source` canonical for photo source (was `--input`/`--library`); `--index`
  (`-i`) for the index DB; `--output` (`-o`, also `--report`) for outputs.

### Fixed
- Album separator contract: `scan_photos_library.py` wrote `"; "` but every
  consumer split on `","` — broke `--prefer-album`/`--album-filter` for
  multi-album photos. Unified to `,`.
- `import_to_photos.py` share workflow: Python f-string referenced an
  AppleScript variable (`thePhotos`) → `NameError`. Fixed to AppleScript.
- `apply_move_plan.move_to_trash()` interpolated paths into AppleScript without
  escaping (injection risk) — now uses shared `escape_applescript()`.
- Album name emoji drift between organizer (`🎬`) and report (`📹`) — unified
  via shared `constants.CATEGORY_ALBUM_NAMES`.
- `--dry-run` album report showed 0 photos / empty diff — now populates
  `added`/`existed` details and simulates before/after album state.
- HTML report paths now absolute so the browser reliably opens them.

## [3.3.0] - 2026-06-15

### Added
- Import photos from external drives/Android into Photos.app with automatic dedup (`import_to_photos.py`)
- Shared album reading from Photos.sqlite
- iCloud sync awareness — detect iCloud-only files and download status
- Checkpoint & resume for import workflow (`--resume` flag + `import_checkpoint.json`)
- Streaming SQLite writes — commit each entry immediately for zero data loss on crash
- `scan_photos_library.py` — open output DB before asset loop, stream entries during iteration
- `scan_photos.py` — extract `_compute_entry()` + `_insert_entry()`, per-entry commit in SQLite mode
- Bilingual README support — `README.md` (English) + `README.zh-CN.md` (Chinese)

### Fixed
- `apply_move_plan.py` — undo was completely broken; `save_undo_record()` now called at end of `main()`
- `apply_move_plan.py` — skipped stats double-counting; photos-trash per-file status tracking
- `generate_preview.py` — XSS prevention via `html.escape()`
- `generate_preview.py` — added `--max-groups` parameter (default 500) to prevent huge HTML files
- `import_to_photos.py` — SIGINT/SIGTERM handler to save checkpoint on Ctrl+C
- `organize_photos.py` — graceful exit when scan finds no photos (prevent OperationalError)

## [3.2.0] - 2026-06-14

### Added
- By-date organize mode — sort photos into `YYYY/MM` folders based on EXIF dates
- By-category organize mode — sort into `01_Photos`, `02_Screenshots`, `03_WeChat`, etc.
- Scan progress bar (5% intervals)
- O(n²) optimization for pHash comparison — index-based SQLite queries
- HEIC preview fix — proper handling of HEIC/HEIF format in thumbnails

## [3.1.0] - 2026-06-13

### Added
- Interactive workflow via `organize_photos.py` — one-command pipeline with step-by-step preferences
- HTML thumbnail preview via `generate_preview.py` — KEEP/MOVE badges, summary stats
- Undo system — `apply_move_plan.py --undo` reverses the most recent move operation
- iCloud download status checking
- Android phone and external drive detection
- 15+ language auto-categorization (Chinese, Japanese, Korean, Russian, French, German, Spanish, Italian, Portuguese, Dutch, Thai, Vietnamese, Bahasa)
- Fast/Safe path confirmation model (1-9 moves brief, 10+ moves require explicit "yes")

## [3.0.0] - 2026-06-12

### Added
- Scaled duplicate detection — same photo at different resolutions
- Cross-format duplicate detection — HEIC + JPEG of the same photo
- Burst detection via EXIF SubSecTime
- Photos.app library scan — read Photos.sqlite directly via `scan_photos_library.py`
- PyObjC deletion from Photos.app (`apply_move_plan.py --mode photos-trash`)
- Match type labels in move plan ("identical pHash", "scaled duplicate", "cross-format duplicate", "burst photo")

## [2.0.0] - 2026-06-11

### Added
- SQLite storage — 400x faster queries for 100k+ photos
- Smart priority rules — multi-factor scoring (resolution, file size, EXIF, format, category, folder)
- macOS Trash mode — recoverable via Finder → Put Back
- GPS metadata extraction — latitude/longitude from EXIF
- Camera metadata extraction — make/model from EXIF
- Auto-categorization — photo, screenshot, WeChat, burst, video
- Space savings report in move plan summary

### Fixed
- IMG_ category misclassification — `IMG_*.JPG` are photos, not screenshots
- Burst priority and folder tiebreaker scoring

## [1.0.0] - 2026-06-10

### Added
- Initial release of SnapTidy — macOS photo/video organizer AI skill
- SHA-256 exact dedup
- pHash perceptual similarity detection
- CSV-based pipeline (scan → dedup → plan → apply)
- Multi-platform AI skill support (Claude Code, Cursor, Windsurf, etc.)
- ClawHub marketplace publishing via `clawhub.yaml`
- CJK + Russian multilingual filename support
