# SnapTidy

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/Platform-macOS-black.svg)](https://www.apple.com/macos)
[![WorkBuddy Skill](https://img.shields.io/badge/WorkBuddy-Skill-purple.svg)](https://codebuddy.cn)

> AI-powered photo & video organizer for macOS. Deduplicate, tidy up, and restructure your library — safely, through conversation.

## Why SnapTidy?

Your photo library grows fast — iPhone shots, iCloud exports, old backups, and screenshots pile up over time. Existing tools like [Sorty](https://github.com/nicoschmdt/sorty), [Tidy](https://github.com/nicoschmdt/tidy), and [Hazelnut](https://github.com/josephearl/hazelnut) are standalone apps you install and configure. **SnapTidy takes a different approach**: it's an AI assistant skill. You describe what you want in natural language, and it handles the rest.

The key difference? **Safety first, zero risk.** SnapTidy never deletes anything. It scans read-only, produces a human-readable CSV plan, and only moves files after you explicitly approve.

## Key Features

- **SHA-256 Exact Dedup** — Find byte-perfect duplicate files across your entire library
- **Perceptual Hash Similarity** — Detect visually identical images using average hash (pHash)
- **Rich Metadata Index** — Extract file size, EXIF dates, dimensions, and hashes into a structured CSV
- **Safety-First Design** — Read-only scanning, move-only operations, CSV-based audit trail
- **Conversation-Driven** — Interact through your AI assistant; no GUI or config files needed
- **Zero Config** — Point at a directory and go. Works with any macOS photo/video folder

## How It Works

```
┌─────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  Scan   │────>│  Find Dupes  │────>│  Gen Plan   │────>│ Review & Apply│
│         │     │              │     │             │     │              │
│ Photos  │     │ SHA-256 +    │     │ CSV move    │     │ You confirm, │
│ & Videos│     │ pHash        │     │ plan        │     │ then it moves │
└─────────┘     └──────────────┘     └─────────────┘     └──────────────┘
  Read-only        Read-only           Read-only          Move-only
```

1. **Scan** — Walk through your photo/video directory, extract metadata (size, SHA-256, EXIF date, dimensions, perceptual hash), and write a CSV index
2. **Find Duplicates** — Group files by exact hash (SHA-256) and perceptual hash (pHash)
3. **Generate Plan** — For each duplicate group, keep one copy and propose moving the rest to a review folder
4. **Review & Apply** — Open the CSV plan, verify everything looks right, then apply. Every action is logged

## Safety Guarantees

| Guarantee | How |
|-----------|-----|
| No automatic deletion | All scripts are read-only by default; `apply_move_plan.py` only moves files |
| Human review required | Move plans are CSV files you can inspect in any spreadsheet app |
| Full audit trail | Every move is logged to `move_log.csv` with source, destination, and status |
| Skip existing files | If a destination file already exists, the move is skipped automatically |
| Photos Library protection | `.photoslibrary` and `.photolibrary` directories are never entered |
| Backup-aware | Directories named `Original_Backup` are automatically skipped |

> See [`references/safety.md`](references/safety.md) for detailed safety guidelines.

## Quick Start

### Prerequisites

- **macOS** (tested on macOS 13+)
- **Python 3.9+**
- **Full Disk Access** enabled for your terminal (System Settings → Privacy & Security → Full Disk Access)

### Install as a WorkBuddy Skill

```bash
# Clone the repo into your WorkBuddy skills directory
git clone https://github.com/chicogong/snaptidy.git ~/.workbuddy/skills/snaptidy

# Install dependencies
cd ~/.workbuddy/skills/snaptidy
pip install -r requirements.txt
```

Then simply tell your AI assistant: *"Scan my photo library at /Volumes/Photos and find duplicates"*

### Manual Usage

```bash
# Step 1: Scan your photo library
python3 scripts/scan_photos.py \
    --input /path/to/your/photos \
    --output ./photo_index.csv

# Step 2: Find exact duplicates
python3 scripts/find_exact_duplicates.py \
    --index ./photo_index.csv \
    --output ./duplicates_exact.csv

# Step 3 (Optional): Find perceptually similar images
python3 scripts/find_similar_photos.py \
    --index ./photo_index.csv \
    --output ./duplicates_similar.csv

# Step 4: Generate a move plan
python3 scripts/generate_move_plan.py \
    --duplicates ./duplicates_exact.csv \
    --plan ./move_plan.csv \
    --target-root /path/to/your/photos

# Step 5: Review move_plan.csv, then apply
python3 scripts/apply_move_plan.py --plan ./move_plan.csv
```

## Supported Formats

| Type | Extensions |
|------|-----------|
| Images | jpg, jpeg, png, bmp, gif, tif, tiff, heic, heif |
| Videos | mov, mp4, m4v, avi, mkv, 3gp, mpg, mpeg |

## Scripts Reference

| Script | Purpose | Input | Output |
|--------|---------|-------|--------|
| `scan_photos.py` | Walk directory tree, extract metadata | Photo/video directory | `photo_index.csv` |
| `find_exact_duplicates.py` | Group byte-identical files by SHA-256 | `photo_index.csv` | `duplicates_exact.csv` |
| `find_similar_photos.py` | Group visually identical images by pHash | `photo_index.csv` | `duplicates_similar.csv` |
| `generate_move_plan.py` | Propose which duplicates to move | Duplicates CSV | `move_plan.csv` |
| `apply_move_plan.py` | Execute the move plan after review | `move_plan.csv` | `move_log.csv` |

## Requirements

- **Pillow** — Image reading, dimensions, format conversion
- **piexif** — EXIF data extraction
- **imagehash** — Perceptual hash computation (average hash)

Only 3 dependencies. No heavy frameworks.

## Contributing

Contributions are welcome! Some areas where help is especially appreciated:

- **Fuzzy perceptual matching** — Add Hamming distance threshold for near-duplicate detection
- **Video deduplication** — Key-frame hashing for video files using ffmpeg/opencv
- **Date-based reorganization** — Sort photos into year/month folders based on EXIF dates
- **Cross-platform support** — Extend beyond macOS to Linux and Windows

Feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Inspired by the macOS automation community and tools like [organize](https://github.com/tfeldmann/organize), [FileLens](https://github.com/priyanshul/get-file-details), and the [Apple CLI](https://github.com/Sankalpcreat/Apple-CLI) ecosystem.
