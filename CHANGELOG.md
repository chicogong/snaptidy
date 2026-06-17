# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
