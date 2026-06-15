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
```

### Option B: One-command interactive workflow

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
```

## Key Flags

| Flag | Description |
|------|-------------|
| `--output .db` vs `.csv` | SQLite (fast, recommended) vs CSV (Excel-compatible) |
| `--threshold N` | pHash Hamming distance (0=exact, 5=fuzzy) |
| `--detect-all` | Run all detection methods (pHash + scaled + cross-format + burst) |
| `--detect-scaled` | Detect scaled duplicates (same photo, different resolution) |
| `--detect-cross-format` | Detect cross-format duplicates (e.g., HEIC + JPEG) |
| `--detect-bursts` | Detect burst photos via SubSecTime EXIF |
| `--strategy quality\|oldest\|newest\|folder` | Priority strategy for keeping duplicates |
| `--prefer-folder "DCIM"` | Extra bonus for specified folder tags |
| `--mode move\|trash\|photos-trash` | Move to review folder / macOS Trash / Photos.app delete |
| `--undo` | Undo the most recent move operation |
| `--interactive` | Run organize_photos.py with step-by-step prompts |
| `--dry-run` | Preview only — scan, detect, plan, but don't apply moves |
| `--check-icloud` | Check iCloud download status of photos |
| `--detect-sources` | Detect Android devices and external drives with photos |
| `--dedup-method` | Choose detection method: exact/phash/scaled/cross-format/burst/all |
| `--trash-mode` | Choose action: move/trash/photos-trash |
| `--mode dedup\|by-date\|by-category\|by-location` | Organize mode: dedup (default), by-date (YYYY/MM), by-category, by-location |

### Import Flags (import_to_photos.py)

| Flag | Description |
|------|-------------|
| `--source PATH` | External source path (folder, DCIM, drive) |
| `--library PATH` | .photoslibrary bundle (auto-detected if omitted) |
| `--album NAME` | Target album in Photos.app (auto-created) |
| `--skip-duplicates` / `--no-skip-duplicates` | Skip/force import of duplicates (default: skip) |
| `--dry-run` | Preview import without actually importing |
| `--method auto\|photoscript\|osascript\|scriptingbridge` | Import method |
| `--report PATH` | Write import report JSON |
| `--detect-sources` | Detect mounted external drives and Android devices |
| `--show-shared-albums` | List shared albums from Photos.sqlite |

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

# Choose import method explicitly
python3 scripts/import_to_photos.py --source /path/to/photos --method osascript
# Methods: auto (default), photoscript (best), osascript (no deps), scriptingbridge (PyObjC)
```

**Important limitations:**
- Shared albums are **READ-ONLY** — cannot add photos via AppleScript
- Import requires Photos.app to be running
- iCloud-synced library: only locally-available files are indexed for dedup
