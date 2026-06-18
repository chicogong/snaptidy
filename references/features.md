# SnapTidy Feature Reference

Detailed feature tables for all versions. See `SKILL.md` for the concise summary.

## v3.14 — Bad Extension Detection & Multi-Dimensional Quality

| Script | Trigger | What it does |
|--------|---------|-------------|
| `detect_bad_extensions.py` | "bad extension", "扩展名校验" | Detect files whose magic bytes don't match their extension; 20+ format signatures (JPEG, PNG, GIF, BMP, TIFF, WebP, HEIC/HEIF, AVIF, MP4/MOV, MKV, WMV, FLV, 3GP, RAW formats); `--parallel`, `--incremental`, `--report` (CSV/JSON) |
| `assess_quality.py` (enhanced) | "照片质量", "quality assessment" | Upgraded from 3 to 7 dimensions: sharpness (25%), exposure (15%), contrast (10%), resolution (15%), format quality (10%), file size efficiency (10%), EXIF completeness (15%); DB stores 7 individual dimension scores + composite `quality_score` |

## v3.13 — Rotation, Conversion & GPS

| Script | Trigger | What it does |
|--------|---------|-------------|
| `rotate_photos.py` | "rotate photo", "照片旋转", "方向纠正" | Batch-rotate photos to correct EXIF Orientation; applies pixel rotation, resets Orientation to 1, preserves EXIF; `--dry-run`, `--orientation N` filter, directory scan |
| `convert_format.py` | "convert format", "格式转换", "JPEG转WEBP" | JPEG/HEIC/PNG → WEBP/AVIF; preserves EXIF GPS/date/camera; 30-50% savings; `--quality N`, `--lossless`, `--keep-originals`, `--dry-run` with savings estimate |
| `fix_gps.py` | "fix gps", "GPS推断", "GPS缺失" | Infer missing GPS from temporally adjacent photos (±10 min); uses closest or averages; `--write-exif`, `--dry-run` |
| `is_animated_image()` | (internal) | Detect GIF/animated WebP/APNG; new `is_animated` DB column; scan reports animated count |
| `get_exif_orientation()` | (internal) | Extract EXIF Orientation (1-8); new `orientation` DB column; scan reports rotated count |
| `Image.MAX_IMAGE_PIXELS` | (internal) | Decompression bomb protection — 60MP limit, prevents OOM from malicious images |
| `AVIF_SUPPORT` | (internal) | AVIF decode support (Pillow ≥11 native or `pillow-avif-plugin`); new `AVIF_EXTS` in constants |

## v3.12 — iCloud Optimization Handling

| Script | Trigger | What it does |
|--------|---------|-------------|
| `icloud_utils.py` | (internal module) | Shared iCloud detection: `.icloud` companion file, xattr, size heuristic; `brctl download` with polling; disk space check |
| `check_icloud.py` | "check icloud", "iCloud优化" | Scan directory for iCloud-only files, report count/size/estimates, **disk space check before download**, batch download with progress, `--max-download N` for limited space, `--min-free GB` safety buffer |
| `scan_photos.py --skip-icloud` | "skip icloud" | Skip iCloud placeholder files during scan |
| `scan_photos.py --download-icloud` | "download icloud" | Trigger `brctl download` for each placeholder, then scan full file |
| `--exclude-icloud` | (dedup flag) | `find_exact_duplicates.py` and `find_similar_photos.py` — skip unreliable placeholder hashes/pHashes |

## v3.11 — Performance & Compression

| Feature | Description |
|---------|-------------|
| `--parallel N` | Parallel scanning (scan_photos.py, assess_quality.py) — 2.9x speedup |
| `--incremental` | Incremental scan — skip unchanged files, 35x faster on re-run |
| `compress_photos.py` | Smart JPEG compression by resolution tier; PNG→JPEG conversion |
| `timeline_gaps.py` | Detect abnormal date gaps indicating missing photos |
| Unified `constants.py` | All format definitions consolidated; AVIF, WebM, MTS, ORF, RW2 added |

## v3.10 — Integrity & Library Health

| Script | Trigger | What it does |
|--------|---------|-------------|
| `detect_corrupted.py` | "corrupted photo", "损坏图片" | Find broken/truncated images, unplayable videos; layered Pillow verify+load, ffmpeg probe; parallel |
| `fix_dates.py` | "fix date", "修正日期" | Fix missing EXIF dates from filename (15+ patterns), neighbor photos, file mtime; supports --dry-run, --write-exif |
| `verify_backup.py` | "backup verify", "备份验证" | Verify backup completeness; quick (filename+size) or full (SHA-256); coverage % |
| `find_duplicate_folders.py` | "duplicate folder", "重复文件夹" | Find similar folders by Jaccard content similarity; near-duplicate grouping |
| `library_stats.py --what-if` | "what if", "空间分析" | "How much space would I save if I delete screenshots/duplicates/RAW?" |
| `--create-event-albums` | "event album" | Create Photos.app albums from cluster_events.py results |

## v3.9 — Advanced Detection & Insights

| Script | Trigger | What it does |
|--------|---------|-------------|
| `assess_quality.py` | "照片质量", "quality assessment" | Blur/brightness/contrast → Q0-100 score, auto-used in dedup strategy & review page; expanded to 7-dimension scoring in v3.14 (see v3.14 section) |
| `detect_live_photos.py` | "Live Photo" | Pairs HEIC+MOV, prevents splitting during dedup |
| `find_orphan_raw.py` | "orphan RAW" | RAW without JPEG companion (or vice versa) |
| `generate_timeline.py` | "timeline", "照片时间线" | Interactive HTML timeline, zoom year/month/day |
| `compare_libraries.py` | "library compare" | Photos.app vs file-system, SHA-256 + filename matching |
| `import_google_takeout.py` | "Google Takeout" | Import Google Photos export, merge JSON metadata to EXIF |
| `gpx_geotag.py` | "GPX geotag" | Assign GPS from GPX track files, interpolation |
| `cluster_events.py` | "event clustering", "照片事件" | Auto-group photos by time + location |
| `find_similar_videos.py` | "video dedup", "视频去重" | Frame sampling + pHash for video duplicates |
| `rename_photos.py` | "smart rename", "照片重命名" | Rename by EXIF date/camera/location: `{date}_{camera}_{seq}` |
