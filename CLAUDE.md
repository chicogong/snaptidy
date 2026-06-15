# SnapTidy — Claude Code Instructions

This project is an AI skill for organizing photos/videos on macOS.

## Key Rules

- Safety first: never delete files, only move them
- All data exchange via CSV files
- Scripts use argparse with `--input`, `--output` style flags
- Test with `python3 scripts/scan_photos.py --input <dir> --output <csv>`
- Full Disk Access must be enabled for the terminal

## Running the Pipeline

```bash
# 1. Scan
python3 scripts/scan_photos.py --input /path/to/photos --output ./photo_index.csv
# 2. Find exact dupes
python3 scripts/find_exact_duplicates.py --index ./photo_index.csv --output ./dupes.csv
# 3. Generate plan
python3 scripts/generate_move_plan.py --duplicates ./dupes.csv --plan ./plan.csv --target-root /path/to/photos
# 4. Apply (only after user review!)
python3 scripts/apply_move_plan.py --plan ./plan.csv
```

## Dependencies

Install with: `pip install -r requirements.txt` (Pillow, piexif, imagehash)
