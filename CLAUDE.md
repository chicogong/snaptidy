# SnapTidy — Claude Code Instructions

This project is an AI skill for organizing photos/videos on macOS.

## Key Rules

- Safety first: never delete files, only move them
- SQLite (.db) is the recommended storage format; CSV is fallback
- Scripts use argparse with `--input`, `--output` style flags
- Full Disk Access must be enabled for the terminal
- For Photos.app libraries, use `scan_photos_library.py` (not `scan_photos.py`)

## Running the Pipeline

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

# 4. Generate plan (with smart priorities)
python3 scripts/generate_move_plan.py \
    --duplicates ./dupes.csv \
    --index ./photo_index.db \
    --plan ./plan.csv \
    --target-root /path/to/photos \
    --prefer-folder "DCIM" --strategy quality

# 5. Apply (only after user review!)
python3 scripts/apply_move_plan.py --plan ./plan.csv --mode trash
# Or for Photos.app managed files:
# python3 scripts/apply_move_plan.py --plan ./plan.csv --mode photos-trash
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
| `--trash` | Shortcut: generate plan with Trash targets |

## Dependencies

Install with: `pip install -r requirements.txt` (Pillow, piexif, imagehash, pillow-heif)
Optional: `pip install pyobjc-framework-Photos` (for Photos.app deletion)
