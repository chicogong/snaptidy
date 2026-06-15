# AGENTS.md — SnapTidy Project Rules

This file provides universal AI coding rules for the SnapTidy project. Compatible with Claude Code, Cursor, GitHub Copilot, Windsurf, and other AI coding agents.

## Project Overview

SnapTidy is a macOS photo/video organizer AI skill. It scans photo libraries, detects duplicates (SHA-256 exact + pHash perceptual + scaled + cross-format + burst), and generates safe move plans. It never deletes files. Supports both file-system scanning and Photos.app library scanning.

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

## Architecture

```
Pipeline: Scan → Dedup → Plan → Apply
          (read)  (read)  (read)  (move-only)

Scan modes:
  scan_photos.py          — File-system scan (exported folders, external drives)
  scan_photos_library.py  — Photos.app library scan (reads Photos.sqlite)

Dedup modes:
  find_exact_duplicates.py  — SHA-256 exact match
  find_similar_photos.py    — pHash + scaled + cross-format + burst
```

Each step is independent and produces a .db/.csv for the next step. This design allows:
- Running any step independently
- Manual review between steps
- Re-running from any point without data loss
- SQLite storage for efficient large-library operations

## Auto-Categorization Rules

Detection order matters (first match wins):
1. **burst**: `_HDR`, `_burst`, `连拍` — checked before screenshot
2. **screenshot**: `screenshot`, `截图`, `截屏`, etc. + iOS `IMG_\d+.PNG`
3. **wechat**: `mmexport`, `wx_camera_`, `microMsg`, `微信`
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
