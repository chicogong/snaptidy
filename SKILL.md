---
name: snaptidy
description: Use when organizing, deduplicating, importing, auditing, repairing, or reporting on macOS photo and video collections, including folders, Photos.app libraries, external drives, Android imports, iCloud placeholders, EXIF or GPS metadata, Live Photos, corrupted media, quality scoring, 整理照片, 照片去重, 整理相册, 修复照片日期, 写真整理, or 사진 정리.
license: MIT
---

# SnapTidy

Organize macOS photo and video collections through a reviewable pipeline:
scan, detect, preview, plan, confirm, apply, and report.

## Safety contract

- Never permanently delete files. SnapTidy may move files to a review folder,
  macOS Trash, or Photos.app Recently Deleted only after confirmation.
- Never modify `.photoslibrary` or `.photolibrary` packages directly. Use
  `scan_photos_library.py` for read-only indexing and Photos APIs for changes.
- Treat scanning, detection, previews, reports, and dry runs as read-only.
- Present the exact plan and obtain explicit confirmation before every move,
  metadata write, Photos.app change, import, or Trash operation.
- Keep the CSV audit trail and report its path after a state-changing operation.
- Detect Live Photo pairs before moving duplicates and keep each pair together.
- Account for iCloud placeholders before comparing hashes or perceptual hashes.
- Never claim all operations share one recovery path. Normal moves, macOS Trash,
  and Photos.app trash use different recovery mechanisms.
- Shared albums are read-only. Do not promise programmatic writes to them.

Read [safety.md](references/safety.md) before any state-changing workflow.

## Start every task

1. Identify the source: normal folder, external drive, Android storage,
   Photos.app library, Google Takeout, or existing SQLite/CSV index.
2. Confirm the host is macOS before using Photos.app, CoreLocation, `brctl`,
   Finder Trash, or AppleScript integrations.
3. Inspect `python3 scripts/<tool>.py --help` before composing uncommon options.
4. Write generated indexes, reports, plans, and logs outside the source tree.
5. Prefer SQLite for large libraries; use CSV only when manual inspection or
   interoperability is more important.
6. Check backups before repair, conversion, rename, import, or move operations.

## Route by intent

| User intent | Start with | Load |
|---|---|---|
| Quick folder duplicate check | `quick_scan.py` | [detection.md](references/detection.md) |
| Full folder organization | `organize_photos.py` or the staged workflow below | [features.md](references/features.md) |
| Photos.app library scan | `scan_photos_library.py` | [safety.md](references/safety.md) |
| Exact, similar, burst, scaled, cross-format, or video matches | `find_exact_duplicates.py` / `find_similar_photos.py` / `find_similar_videos.py` | [detection.md](references/detection.md) |
| Interactive review with keyboard shortcuts | `generate_review.py` | [features.md](references/features.md) |
| Bad extension / mismatched content | `detect_bad_extensions.py` | [features.md](references/features.md) |
| Corrupted or unplayable media | `detect_corrupted.py` | [features.md](references/features.md) |
| Library health report and space analysis | `library_stats.py` | [features.md](references/features.md) |
| Interactive timeline view | `generate_timeline.py` | [features.md](references/features.md) |
| Timeline gap detection (missing photos) | `timeline_gaps.py` | [features.md](references/features.md) |
| Compress photos to save space | `compress_photos.py` | [features.md](references/features.md) |
| Format conversion (JPEG/HEIC → WEBP/AVIF) | `convert_format.py` | [features.md](references/features.md) |
| Backup completeness verification | `verify_backup.py` | [features.md](references/features.md) |
| Duplicate folder detection | `find_duplicate_folders.py` | [features.md](references/features.md) |
| Orphan RAW cleanup | `find_orphan_raw.py` | [features.md](references/features.md) |
| External drive, Android, or Google Takeout import | `import_to_photos.py` / `import_google_takeout.py` | [import.md](references/import.md) |
| EXIF, date, GPS, orientation, reverse geocode, or GPX work | `edit_exif.py`, `fix_dates.py`, `fix_gps.py`, `rotate_photos.py`, `reverse_geocode.py`, `gpx_geotag.py` | [exif-editing.md](references/exif-editing.md), [geocoding.md](references/geocoding.md) |
| Privacy risk detection | `detect_privacy_risks.py` | [features.md](references/features.md) |
| Smart rename using metadata | `rename_photos.py` | [features.md](references/features.md) |
| Event clustering by time and location | `cluster_events.py` | [features.md](references/features.md) |
| Photos.app vs file-system comparison | `compare_libraries.py` | [features.md](references/features.md) |
| Album organization report (before/after diff) | `generate_album_report.py` | [features.md](references/features.md) |
| iCloud placeholder check or pre-download | `check_icloud.py` | [features.md](references/features.md) |
| Performance or very large libraries | parallel/incremental flags | [performance.md](references/performance.md) |
| Failure or missing dependency | relevant tool `--help` | [troubleshooting.md](references/troubleshooting.md) |

Use `python3 scripts/quick_scan.py --help` for the zero-install path. Install
optional packages from `requirements.txt` only when the chosen detection or
metadata workflow needs them.

## Default dedup workflow

Keep the workflow read-only through plan generation.

### 1. Scan

For a normal folder:

```bash
python3 scripts/scan_photos.py \
  --source /path/to/photos \
  --output ./snaptidy-output/photo_index.db
```

For Photos.app, point the library scanner at the library package; do not run the
folder scanner inside it:

```bash
python3 scripts/scan_photos_library.py \
  --source "$HOME/Pictures/Photos Library.photoslibrary" \
  --output ./snaptidy-output/photo_index.db
```

### 2. Detect

```bash
python3 scripts/find_exact_duplicates.py \
  --index ./snaptidy-output/photo_index.db \
  --output ./snaptidy-output/exact.csv \
  --exclude-icloud

python3 scripts/find_similar_photos.py \
  --index ./snaptidy-output/photo_index.db \
  --output ./snaptidy-output/similar.csv \
  --detect-all \
  --exclude-icloud
```

Run `detect_live_photos.py` before planning moves when the collection may
contain HEIC+MOV Live Photos. Run `assess_quality.py` before using the `quality`
strategy.

### 3. Preview and plan

```bash
python3 scripts/generate_move_plan.py \
  --duplicates ./snaptidy-output/similar.csv \
  --index ./snaptidy-output/photo_index.db \
  --plan ./snaptidy-output/move_plan.csv \
  --target-root ./snaptidy-output/review \
  --strategy quality

python3 scripts/generate_preview.py \
  --duplicates ./snaptidy-output/similar.csv \
  --index ./snaptidy-output/photo_index.db \
  --plan ./snaptidy-output/move_plan.csv \
  --output ./snaptidy-output/preview.html
```

**Plan strategies** (`--strategy`): `quality` (keep highest score, requires
`assess_quality.py` first) · `oldest` (keep earliest capture) · `newest`
(keep latest) · `folder` (keep deepest nested). Use `generate_review.py`
for an interactive review page with keyboard shortcuts before applying.

Summarize file counts, match types, bytes affected, keep/move decisions,
destination, iCloud exclusions, and Live Photo handling before asking to apply.

## Confirmation and recovery

- For 1–9 planned moves, show the plan summary and request `[Y/n]` confirmation.
- For 10 or more moves, require the user to type `yes`; do not infer consent.
- After confirmation, apply normal folder moves with:

```bash
python3 scripts/apply_move_plan.py \
  --plan ./snaptidy-output/move_plan.csv \
  --mode move
```

- Normal folder moves create a 30-day undo record. Reverse the latest eligible
  move with `python3 scripts/apply_move_plan.py --plan <plan.csv> --undo`.
- Trash operations cannot be undone with `--undo`. Recover macOS Trash items
  with Finder > Put Back.
- Recover Photos.app trash operations from Photos.app > Recently Deleted while
  the system retention window still applies.

## Completion report

State:

- Which source and scan mode were used.
- Which index, duplicate reports, previews, and plans were created.
- Whether files or metadata changed; never imply a plan was already applied.
- The number of successful, skipped, and failed actions.
- The audit log and undo-record paths, when applicable.
- The exact recovery action for the selected operation mode.
