---
name: snaptidy
description: |
  A safety‑first photo‑organising skill for macOS that builds a rich metadata index, detects duplicates and proposes a move plan – without ever deleting your originals.  
  Designed to complement other Apple automation skills (e.g. **apple‑cli**, **memo**, **remindctl**) and work with exported Photos libraries, it helps you prepare clean archives and clear inboxes.  
  Invoke this skill when you need to scan and tidy large photo/video folders, deduplicate archives, suggest a folder structure or generate a report for human review.  
---

# Mac Personal Organizer Skill

## Overview

Modern photo libraries often span iPhone snapshots, iCloud exports, external drives and legacy backups.  Over time they accumulate duplicate shots, bursts, screenshots and random clutter.  This skill implements a reproducible workflow to **scan and analyse** those files safely.  The provided scripts:

* Walk through a folder tree and write a CSV index containing metadata such as size, SHA‑256 digest, EXIF capture date, dimensions and an average perceptual hash.
* Group files with identical hashes to find **exact duplicates** and group identical perceptual hashes for conservative similarity detection.
* Generate a **move plan** that keeps one copy of each duplicate group and moves the rest into a designated `_待确认` directory, ready for review.

No files are deleted automatically; every action is recorded in a report.  This skill fills the gap between general Apple automation (Notes, Reminders, Calendar) and photo management by providing the photo‑organising piece.

## Safety rules

- **Never delete originals** – all scripts operate in read‑only mode.  Move operations are emitted into a plan file (`move_plan.csv`) but never executed by default.  Only an explicit call to `apply_move_plan.py` will perform moves, and even then files are moved rather than removed.
- **Stay out of Photos Libraries** – do not descend into files ending with `.photoslibrary` or `.photolibrary`.  These are managed by Photos.app and should not be modified directly.  If scanning an exported set from Photos.app, point the scan at the exported folder, not the library package.
- **Operate only inside user‑provided paths** – never scan system directories or arbitrary disk roots.  The user must explicitly supply the path to scan.
- **Respect external backups** – do not modify files on backup drives.  If a target directory ends with `99_Original_Backup_勿动` (or similar), skip it.
- **Ask before moving** – always present the generated report and move plan to the user and ask for confirmation before running `apply_move_plan.py`.

## Installation

This skill requires Python 3.8 or higher and several Python packages.  From the root of this skill directory run:

```bash
pip install -r requirements.txt
```

The dependencies are **Pillow** (for image metadata), **piexif** (EXIF extraction) and **imagehash** (perceptual hashing).

## Usage

1. **Scan a folder**.  Use `scripts/scan_photos.py` with the path to your photo/video directory and an output CSV path:

   ```bash
   python3 scripts/scan_photos.py --input /Volumes/Photo_Master/00_Inbox_待整理 \
       --output /Volumes/Photo_Master/90_Reports/photo_index.csv
   ```

   This walks the directory tree, extracts metadata (file size, SHA‑256, EXIF date, dimensions, perceptual hash) and writes a CSV index.

2. **Find exact duplicates**.  Once indexed, run `scripts/find_exact_duplicates.py` to identify files with identical SHA‑256 hashes:

   ```bash
   python3 scripts/find_exact_duplicates.py --index /Volumes/Photo_Master/90_Reports/photo_index.csv \
       --output /Volumes/Photo_Master/90_Reports/duplicates_exact.csv
   ```

3. **Find perceptually identical files** (optional).  Use `find_similar_photos.py` to group images with matching perceptual hashes (very conservative):

   ```bash
   python3 scripts/find_similar_photos.py --index /Volumes/Photo_Master/90_Reports/photo_index.csv \
       --output /Volumes/Photo_Master/90_Reports/duplicates_similar.csv
   ```

4. **Generate a move plan**.  Combine the reports into a suggested reorganisation.  For example, move exact duplicates into a `06_Duplicates_待确认删除` folder.  Use `scripts/generate_move_plan.py`:

   ```bash
   python3 scripts/generate_move_plan.py \
       --duplicates /Volumes/Photo_Master/90_Reports/duplicates_exact.csv \
       --plan /Volumes/Photo_Master/90_Reports/move_plan.csv \
       --target-root /Volumes/Photo_Master
   ```

5. **Review the plan**.  Open `move_plan.csv` and confirm that the proposed moves are correct.  If necessary, edit the plan manually or regenerate it with different rules.

6. **Apply the move plan** (optional).  Once you are comfortable, run:

   ```bash
   python3 scripts/apply_move_plan.py --plan /Volumes/Photo_Master/90_Reports/move_plan.csv
   ```

   This will move files according to the plan, creating directories as needed and logging every operation to `move_log.csv`.  It never deletes files and will skip moves if the destination already exists.

## Integration with other skills

This photo organiser is intended to be used alongside other macOS automation skills:

- **apple‑cli** (Notes/Reminders/Calendar/Messages) – use this skill to add notes about which folders were processed or to create reminders to review duplicates.  For example, after generating a report, call `apple reminders create` to remind yourself to check `move_plan.csv`【986209175665060†L334-L365】.
- **openclaw memo/remindctl** – these CLI tools expose similar functionality for Apple Notes and Reminders【791548240194761†L75-L83】.  You can invoke them from your automation scripts to log the status of your photo organisation project.
- **shortcuts‑bridge‑codex** – if you have macOS Shortcuts that perform backups or copy files to external drives, call them via this skill’s local HTTP bridge【455977436621876†L70-L80】.

## Limitations and future work

- Perceptual similarity detection in `find_similar_photos.py` currently groups only images with identical pHashes.  This is conservative and may miss near duplicates; a more advanced implementation could use Hamming distance or CLIP embeddings.
- Video files are indexed for size and hash but are not analysed for similarity.  Extending the scripts with tools like `ffmpeg` or `opencv` would enable deduplication of videos.
- This skill does not manage cross‑device file transfers.  For moving photos between macOS and Android/iOS, consider using applications like **MacDroid** or **EasyJoin**【916029002888395†L64-L99】【444114619710389†L60-L90】 and then run this skill on the consolidated archive.
- Always back up your data before applying any move plan.  See `references/safety.md` for more guidelines.

## File structure

```
snaptidy/
  SKILL.md              # this document
  requirements.txt      # Python dependencies
  scripts/              # Python utilities for scanning and organising
    scan_photos.py
    find_exact_duplicates.py
    find_similar_photos.py
    generate_move_plan.py
    apply_move_plan.py
  references/
    safety.md           # best practices and additional notes
```