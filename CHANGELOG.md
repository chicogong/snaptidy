# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
