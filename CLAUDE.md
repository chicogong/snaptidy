# SnapTidy — Claude Code Instructions

This project is an AI skill for organizing photos/videos on macOS.

## Key Rules

- Safety first: never delete files, only move them
- SQLite (.db) is the recommended storage format; CSV is fallback
- Scripts use argparse with `--input`, `--output` style flags
- Full Disk Access must be enabled for the terminal

## Running the Pipeline

```bash
# 1. Scan (SQLite recommended)
python3 scripts/scan_photos.py --input /path/to/photos --output ./photo_index.db

# 2. Find exact dupes
python3 scripts/find_exact_duplicates.py --index ./photo_index.db --output ./dupes.csv

# 3. Find similar (optional, pHash)
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --threshold 5

# 4. Generate plan (with smart priorities)
python3 scripts/generate_move_plan.py \
    --duplicates ./dupes.csv \
    --index ./photo_index.db \
    --plan ./plan.csv \
    --target-root /path/to/photos \
    --prefer-folder "DCIM" --strategy quality

# 5. Apply (only after user review!)
python3 scripts/apply_move_plan.py --plan ./plan.csv --mode trash
```

## Key Flags

| Flag | Description |
|------|-------------|
| `--output .db` vs `.csv` | SQLite (fast, recommended) vs CSV (Excel-compatible) |
| `--threshold N` | pHash Hamming distance (0=exact, 5=fuzzy) |
| `--strategy quality\|oldest\|newest\|folder` | Priority strategy for keeping duplicates |
| `--prefer-folder "DCIM"` | Extra bonus for specified folder tags |
| `--mode move\|trash` | Move to review folder or macOS Trash |
| `--trash` | Shortcut: generate plan with Trash targets |

## Dependencies

Install with: `pip install -r requirements.txt` (Pillow, piexif, imagehash)
