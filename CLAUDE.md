# SnapTidy — Claude Code Instructions

This project is an AI skill for organizing photos/videos on macOS.

## Key Rules

- Safety first: never delete files, only move them
- SQLite (.db) is the recommended storage format; CSV is fallback
- Scripts use argparse with `--input`, `--output` style flags
- Full Disk Access must be enabled for the terminal
- For Photos.app libraries, use `scan_photos_library.py` (not `scan_photos.py`)
- Always confirm before applying moves: Fast path (1-9) or Safe path (10+)
- Always inform user about `--undo` after applying moves
- Scan writes commit each entry immediately — zero data loss on crash

## Running the Pipeline

### Option A: Step-by-step (full control)

```bash
# 1a. Scan file-system folders
python3 scripts/scan_photos.py --input /path/to/photos --output ./photo_index.db

# 1b. Scan Photos.app library (reads Photos.sqlite)
python3 scripts/scan_photos_library.py --library ~/Pictures/Photos\ Library.photoslibrary --output ./photo_index.db

# 2. Find exact dupes
python3 scripts/find_exact_duplicates.py --index ./photo_index.db --output ./dupes.csv

# 3. Find similar (all methods: pHash + scaled + cross-format + burst)
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --detect-all

# Individual methods:
# python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --detect-scaled
# python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --detect-cross-format
# python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --detect-bursts

# 4. Preview with HTML thumbnails (optional but recommended)
python3 scripts/generate_preview.py --duplicates ./similar.csv --index ./photo_index.db --output ./preview.html
# With move plan overlay:
# python3 scripts/generate_preview.py --duplicates ./similar.csv --index ./photo_index.db --plan ./plan.csv --output ./preview.html

# 4b. Interactive review with smart rules (recommended for cleanup)
python3 scripts/generate_review.py \
    --index ./photo_index.db \
    --duplicates ./dupes.csv \
    --similar ./similar.csv \
    --output ./review.html
# → Open review.html in browser, mark keep/remove, export decision CSV

# 5. Generate plan (with smart priorities)
python3 scripts/generate_move_plan.py \
    --duplicates ./dupes.csv \
    --index ./photo_index.db \
    --plan ./plan.csv \
    --target-root /path/to/photos \
    --prefer-folder "DCIM" --strategy quality

# 6. Apply (only after user review!)
python3 scripts/apply_move_plan.py --plan ./plan.csv --mode trash
# Or for Photos.app managed files:
# python3 scripts/apply_move_plan.py --plan ./plan.csv --mode photos-trash

# 7. Undo if needed
python3 scripts/apply_move_plan.py --plan ./plan.csv --undo

# 8. Assess quality (blur/brightness/contrast → DB columns)
python3 scripts/assess_quality.py --index ./photo_index.db

# 9. Detect Live Photo pairs
python3 scripts/detect_live_photos.py --index ./photo_index.db

# 10. Generate timeline view
python3 scripts/generate_timeline.py --index ./photo_index.db --output ./timeline.html

# 11. Find orphan RAW files
python3 scripts/find_orphan_raw.py --index ./photo_index.db --output ./orphan.csv

# 12. Cluster into events
python3 scripts/cluster_events.py --index ./photo_index.db --output events.json --write-db

# 13. Find similar videos (requires ffmpeg)
python3 scripts/find_similar_videos.py --index ./photo_index.db --output ./video_dupes.csv

# 14. Smart rename (dry-run first)
python3 scripts/rename_photos.py --index ./photo_index.db --template "{date}_{camera}_{seq}"

# 15. GPX geotag photos without GPS
python3 scripts/gpx_geotag.py --index ./photo_index.db --gpx track.gpx --dry-run

# 16. Compare Photos.app vs file-system
python3 scripts/compare_libraries.py --library ~/Pictures/Photos\ Library.photoslibrary --index ./photo_index.db --output comparison.json

# 17. Import Google Takeout
python3 scripts/import_google_takeout.py --source ~/Downloads/takeout --output ./takeout_index.db
```

### Option B: Full pipeline with v3.9 enhancements

```bash
# Scan + quality + Live Photo + events + timeline in one command
python3 scripts/organize_photos.py --source ~/Pictures/Export \
  --assess-quality --detect-live-photos --cluster-events \
  --generate-timeline --strategy quality --dry-run

# All enhancements enabled
python3 scripts/organize_photos.py --source ~/Pictures/Export \
  --assess-quality --detect-live-photos --cluster-events \
  --generate-timeline --find-orphan-raw --smart-rename \
  --strategy quality --dry-run
```

### Option C: One-command interactive workflow

```bash
# Interactive — asks preferences step by step
python3 scripts/organize_photos.py --source ~/Pictures/Export --interactive

# Non-interactive with dry-run
python3 scripts/organize_photos.py \
    --source ~/Pictures/Export \
    --dedup-method all \
    --strategy quality \
    --trash-mode trash \
    --dry-run

# Detect external drives and Android devices
python3 scripts/organize_photos.py --source /any --detect-sources

# Check iCloud download status
python3 scripts/organize_photos.py --source ~/Pictures/Export --check-icloud

# Organize by date into YYYY/MM folders
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-date --dry-run

# Organize by category (01_Photos, 02_Screenshots, 03_WeChat, etc.)
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-category --dry-run

# Organize by location (Country/Region/City/)
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-location --dry-run
```

## Key Flags

| Flag | Description |
|------|-------------|
| `--output .db` vs `.csv` | SQLite (fast, recommended) vs CSV (Excel-compatible) |
| `--threshold N` | pHash Hamming distance (0=exact, 5=fuzzy) |
| `--detect-all` | Run all detection methods |
| `--detect-scaled` | Detect scaled duplicates |
| `--detect-cross-format` | Detect cross-format duplicates (e.g., HEIC + JPEG) |
| `--detect-bursts` | Detect burst photos via SubSecTime EXIF |
| `--strategy quality\|oldest\|newest\|folder` | Priority strategy |
| `--prefer-folder "DCIM"` | Extra bonus for specified folder tags |
| `--mode move\|trash\|photos-trash` | Move to folder / Trash / Photos.app delete |
| `--undo` | Undo the most recent move operation |
| `--interactive` | Run organize_photos.py with step-by-step prompts |
| `--dry-run` | Preview only — scan, detect, plan, but don't apply |
| `--check-icloud` | Check iCloud download status |
| `--detect-sources` | Detect Android devices and external drives |
| `--dedup-method` | Detection method: exact/phash/scaled/cross-format/burst/all |
| `--trash-mode` | Action: move/trash/photos-trash |
| `--mode dedup\|by-date\|by-category\|by-location` | Organize mode |
| `--no-geocode` | Disable reverse geocoding during scan |
| `--geocode` | Enable reverse geocoding (default) |

### EXIF Editing Flags (edit_exif.py)

| Flag | Description |
|------|-------------|
| `strip-gps` | Remove GPS data from indexed photos |
| `set-date` | Set EXIF capture date on specific files |
| `set-tags` | Write keywords/tags to photo EXIF |
| `--index PATH` | SQLite index DB for batch strip-gps |
| `--only-gps` | Only strip GPS from photos that have GPS data |
| `--date ISO` | Date to set (ISO 8601 format) |
| `--tags CSV` | Comma-separated tags to write |
| `--paths FILES` | Specific file paths to modify |
| `--no-backup` | Skip backup creation (faster, less safe) |

### Import Flags (import_to_photos.py)

| Flag | Description |
|------|-------------|
| `--source PATH` | External source path |
| `--library PATH` | .photoslibrary bundle (auto-detected if omitted) |
| `--album NAME` | Target album in Photos.app (auto-created) |
| `--skip-duplicates` / `--no-skip-duplicates` | Skip/force import of duplicates |
| `--dry-run` | Preview import without actually importing |
| `--method auto\|photoscript\|osascript\|scriptingbridge` | Import method |
| `--report PATH` | Write import report JSON |
| `--detect-sources` | Detect mounted external drives and Android |
| `--show-shared-albums` | List shared albums from Photos.sqlite |
| `--resume` | Resume interrupted import from checkpoint |

## Dependencies

Install with: `pip install -r requirements.txt` (Pillow, piexif, imagehash, pillow-heif)
Optional: `pip install pyobjc-framework-Photos` (for Photos.app deletion)
Optional: `pip install photoscript` (for Photos.app import — recommended)

## Import from External Sources

Import photos from hard drives or Android phones into Photos.app with automatic dedup:

```bash
# Dry-run: preview what would be imported
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --dry-run

# Import all unique photos (duplicates skipped automatically)
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --album "Vacation 2025"

# Import from Android DCIM
python3 scripts/import_to_photos.py --source /Volumes/Android/DCIM --album "Android Import"

# Detect connected external sources
python3 scripts/import_to_photos.py --detect-sources

# List shared albums (read-only)
python3 scripts/import_to_photos.py --show-shared-albums

# Resume interrupted import
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --resume
```

**Important limitations:**
- Shared albums are **READ-ONLY** — cannot add photos via AppleScript
- Import requires Photos.app to be running
- iCloud-synced library: only locally-available files are indexed for dedup

## Reverse Geocoding & By-Location Organize

```bash
# Scan with geocoding (default — populates place_city/region/country columns)
python3 scripts/scan_photos.py --source ~/Photos --output ./index.db

# Disable geocoding for faster scan
python3 scripts/scan_photos.py --source ~/Photos --output ./index.db --no-geocode

# Query a single GPS coordinate
python3 scripts/reverse_geocode.py --lat 39.90 --lon 116.41

# Organize by location (Country/Region/City/filename)
python3 scripts/organize_photos.py --source ~/Photos --mode by-location --dry-run
```

## EXIF Editing

```bash
# Strip GPS data from indexed photos (dry-run first!)
python3 scripts/edit_exif.py strip-gps --index ./index.db --dry-run
python3 scripts/edit_exif.py strip-gps --index ./index.db --only-gps

# Set EXIF date on specific files
python3 scripts/edit_exif.py set-date --date "2025-06-15T14:30:00" --paths photo1.jpg photo2.heic

# Write tags/keywords
python3 scripts/edit_exif.py set-tags --tags "vacation,beach,summer" --paths photo1.jpg
```

Safety: `.bak` backup created before edit, restored on error, cleaned on success.
