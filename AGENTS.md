# AGENTS.md — SnapTidy Project Rules

This file provides universal AI coding rules for the SnapTidy project. Compatible with Claude Code, Cursor, GitHub Copilot, Windsurf, and other AI coding agents.

## Project Overview

SnapTidy is a macOS photo/video organizer AI skill. It scans photo libraries, detects duplicates (SHA-256 exact + pHash perceptual + scaled + cross-format + burst), generates safe move plans, provides HTML thumbnail previews, and supports undo. It never deletes files. Supports both file-system scanning and Photos.app library scanning. Interactive one-command workflow via `organize_photos.py`.

## Code Conventions

- **Language**: Python 3.9+
- **Style**: PEP 8, 4-space indent, max line length 120
- **Scripts**: All scripts under `scripts/` are CLI tools using `argparse`
- **Input/Output**: SQLite (.db) or CSV (.csv) — SQLite preferred for 100k+ photos
- **Encoding**: All CSV files use UTF-8 with BOM for Excel compatibility

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
Pipeline: Scan → Dedup → Preview → Plan → Apply → Undo
          (read)  (read)  (read)   (read)  (move)  (reverse)

Scan modes:
  scan_photos.py          — File-system scan (exported folders, external drives)
  scan_photos_library.py  — Photos.app library scan (reads Photos.sqlite)

Dedup modes:
  find_exact_duplicates.py  — SHA-256 exact match
  find_similar_photos.py    — pHash + scaled + cross-format + burst

Preview:
  generate_preview.py       — HTML thumbnail preview (KEEP/MOVE badges)

Plan:
  generate_move_plan.py     — Smart priority move plan generation

Apply:
  apply_move_plan.py        — Move/trash/photos-trash + undo support

Interactive:
  organize_photos.py        — One-command pipeline (collect prefs → scan → detect → preview → plan → confirm → apply)
```

Each step is independent and produces a .db/.csv for the next step. This design allows:
- Running any step independently
- Manual review between steps
- Re-running from any point without data loss
- SQLite storage for efficient large-library operations
- HTML preview for visual review before committing

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
- Location: gps_latitude, gps_longitude
- Camera: camera_make, camera_model
- Priority: folder_tag, scan_root, scanned_at
- Photos.app exclusive: photos_favorite, photos_hidden, photos_screenshot, photos_duplicate_visibility, photos_cloud_state, photos_albums

Schema migration: `ALTER TABLE ADD COLUMN` with try/except (backward compatible).

## Dependencies

- Pillow: Image reading and metadata
- piexif: EXIF data extraction (including SubSecTime)
- imagehash: Perceptual hash computation
- pillow-heif: Optional HEIC/HEIF image support
- pyobjc-framework-Photos: Optional Photos.app PyObjC deletion

Do NOT add pandas, numpy, or other heavy dependencies unless absolutely necessary.
