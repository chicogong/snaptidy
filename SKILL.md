---
name: snaptidy
version: 1.0.0
description: |
  AI-powered photo & video organizer for macOS. Scan libraries, detect duplicates (SHA-256 exact + pHash perceptual), and generate safe move plans — without ever deleting your originals.
  Use this skill when you need to: scan and tidy large photo/video folders, find duplicate photos, deduplicate archives, organize a messy photo library, or generate a dedup report for human review.
  Trigger phrases: "organize my photos", "find duplicate photos", "dedup my library", "tidy photo folder", "scan for duplicates"
author: chicogong
license: MIT
homepage: https://github.com/chicogong/snaptidy
compatibility: "Claude Code, Cursor, Windsurf, OpenClaw, WorkBuddy, Cline, Aider"
metadata:
  openclaw:
    always: false
    emoji: "🗂️"
    os:
      - darwin
    requires:
      bins:
        - python3
    install:
      - kind: pip
        packages: [Pillow, piexif, imagehash]
---

# SnapTidy — Photo & Video Organizer

## When to Use

Invoke this skill when the user asks to:
- Organize or tidy up photo/video folders on macOS
- Find and remove duplicate photos
- Scan a photo library for duplicates
- Generate a dedup report or move plan
- Prepare a clean photo archive

## Safety Rules (MANDATORY)

- **Never delete originals** — all scripts are read-only by default. Only `apply_move_plan.py` moves files (never deletes).
- **Stay out of Photos Libraries** — never enter `.photoslibrary` or `.photolibrary` directories. Always scan exported folders.
- **Operate only inside user-provided paths** — never scan system directories or disk roots.
- **Respect external backups** — skip directories named `Original_Backup` or similar.
- **Ask before moving** — always present the move plan CSV and get user confirmation before running `apply_move_plan.py`.

## Process

### Step 1: Install Dependencies

If Python packages are not installed, run:

```bash
pip install -r requirements.txt
```

Dependencies: **Pillow** (image metadata), **piexif** (EXIF extraction), **imagehash** (perceptual hashing).

### Step 2: Scan the Photo Library

```bash
python3 scripts/scan_photos.py --input <photo_directory> --output <output_csv>
```

This walks the directory tree, extracts metadata (file size, SHA-256, EXIF date, dimensions, perceptual hash), and writes a CSV index.

### Step 3: Find Duplicates

**Exact duplicates** (SHA-256):

```bash
python3 scripts/find_exact_duplicates.py --index <index_csv> --output <duplicates_csv>
```

**Perceptually similar** (pHash, optional):

```bash
python3 scripts/find_similar_photos.py --index <index_csv> --output <similar_csv>
```

### Step 4: Generate Move Plan

```bash
python3 scripts/generate_move_plan.py \
    --duplicates <duplicates_csv> \
    --plan <move_plan_csv> \
    --target-root <photo_directory>
```

This proposes keeping one copy from each duplicate group and moving the rest to a `06_Duplicates_待确认删除/` folder.

### Step 5: Review and Apply

1. Open the generated `move_plan.csv` — verify every proposed move
2. Present the plan summary to the user
3. Only after explicit confirmation, apply:

```bash
python3 scripts/apply_move_plan.py --plan <move_plan_csv>
```

Every move is logged to `move_log.csv`. If a destination file already exists, the move is skipped.

## Supported Formats

| Type | Extensions |
|------|-----------|
| Images | jpg, jpeg, png, bmp, gif, tif, tiff, heic, heif |
| Videos | mov, mp4, m4v, avi, mkv, 3gp, mpg, mpeg |

## Troubleshooting

- **Permission denied**: Ensure Full Disk Access is enabled for the terminal (System Settings → Privacy & Security → Full Disk Access)
- **No EXIF data**: Some images (screenshots, downloaded photos) may lack EXIF. The scan still captures file size, hash, and dimensions.
- **pHash false positives**: Solid-color or very simple images may produce identical pHash values. Use exact duplicate detection (SHA-256) as the primary method.
- **`pip install` fails**: Ensure Python 3.9+ is installed (`python3 --version`). On macOS, you may need `xcode-select --install` first.
