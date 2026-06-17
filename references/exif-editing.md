# EXIF Editing

## Overview

SnapTidy can modify photo EXIF metadata through `edit_exif.py`. Three operations are supported: strip GPS data, set capture dates, and write tags/keywords. All operations include backup/restore safety mechanisms.

## Operations

### 1. Strip GPS (`strip-gps`)

Remove GPS coordinates from photos in the scan index:

```bash
# Dry-run (preview only, no changes)
python3 scripts/edit_exif.py strip-gps --index ./photo_index.db --dry-run

# Actually strip GPS from all indexed photos
python3 scripts/edit_exif.py strip-gps --index ./photo_index.db

# Only strip GPS from photos that have GPS coordinates
python3 scripts/edit_exif.py strip-gps --index ./photo_index.db --only-gps
```

- Reads the SQLite index to find all photo paths
- When `--only-gps` is used, only processes photos where `gps_latitude`/`gps_longitude` are non-empty
- Reports how many files had GPS stripped vs skipped

### 2. Set Date (`set-date`)

Set EXIF capture date on specific files:

```bash
python3 scripts/edit_exif.py set-date --date "2025-06-15T14:30:00" --paths photo1.jpg photo2.heic
```

- Writes to `Exif.Photo.DateTimeOriginal` and `Exif.Photo.DateTimeDigitized`
- Date format: ISO 8601 (`YYYY-MM-DDTHH:MM:SS`)

### 3. Set Tags (`set-tags`)

Write keywords/tags to photo EXIF:

```bash
python3 scripts/edit_exif.py set-tags --tags "vacation,beach,summer" --paths photo1.jpg photo2.jpg
```

- Writes to `Iptc.Application2.Keywords` (IPTC standard)
- Tags are comma-separated

## Safety Mechanisms

### Backup/Restore Pattern

1. **Before edit**: A `.bak` copy of the original file is created
2. **On success**: The `.bak` file is cleaned up
3. **On error**: The `.bak` file is restored to the original path

```bash
# Disable backup (faster, less safe — use only when you're confident)
python3 scripts/edit_exif.py strip-gps --index index.db --no-backup
```

### Dry-Run

All operations support `--dry-run` to preview changes without modifying files:

```bash
python3 scripts/edit_exif.py strip-gps --index index.db --dry-run
python3 scripts/edit_exif.py set-date --date "2025-06-15" --paths photo.jpg --dry-run
python3 scripts/edit_exif.py set-tags --tags "test" --paths photo.jpg --dry-run
```

## Format Support

| Format | Engine | Notes |
|--------|--------|-------|
| JPEG | piexif | Native Python EXIF library |
| TIFF | piexif | Same as JPEG |
| HEIC | exiftool (fallback) | Requires `exiftool` installed |
| RAW (CR2/NEF/ARW/DNG) | exiftool (fallback) | Requires `exiftool` installed |

If `exiftool` is not installed and the file is HEIC/RAW, the operation is skipped with a warning.

## Dependencies

- **piexif** (required for JPEG/TIFF) — `pip install piexif`
- **exiftool** (optional, for HEIC/RAW) — Install via `brew install exiftool`

If piexif is not installed, all EXIF editing operations will fail with an error message.
