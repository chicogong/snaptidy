---
name: snaptidy
version: 3.7.0
description: |
  AI-powered photo & video organizer for macOS. Detect duplicates using SHA-256 exact + pHash perceptual + scaled + cross-format (HEIC↔JPEG) + burst + Apple Quality Vector + CNN. Scan file folders or Photos.app library. Import from external drives/Android into Photos.app with automatic dedup. Organize by date/category, create albums in Photos.app, library health & insights report, HTML before/after report, interactive workflow, HTML thumbnail preview, undo support, iCloud/Android/external drive detection, shared album reading, album-aware filtering, smart priority rules with album/folder preference, Fast/Safe path confirmation, SQLite storage for 100k+ photos.
  Trigger: "organize my photos", "find duplicate photos", "dedup my library", "tidy photo folder", "import photos", "import from Android", "整理照片", "去重", "整理相册", "HEIC去重", "写真整理", "사진 정리", "按日期整理照片", "organize by date", "导入照片", "清理相册", "album dedup", "创建相册", "归类相册", "相册分类", "按类别整理", "按格式分类", "album organization", "organize albums", "photos album", "相册报告", "整理报告", "照片库健康", "library health", "library stats", "照片统计", "library insights", "照片库分析"
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
        packages: [Pillow, piexif, imagehash, pillow-heif]
---

# SnapTidy — Photo & Video Organizer

## When to Use

Organize/tidy photo folders, find/remove duplicates, scan Photos.app library, detect scaled/cross-format/burst duplicates, generate move plans, preview with HTML thumbnails, undo moves, check iCloud status, scan Android/external drives, import into Photos.app with dedup, read shared albums, filter by album, **create albums in Photos.app by date/category/format**, **HTML before/after diff report**, **library health & insights (read-only stats)**.

**Triggers:** 整理照片 · 去重 · 整理相册 · 重複写真を削除 · 사진 정리 · Organiser mes photos · Fotos organisieren · Organizar fotos · 清理相册 · 照片库健康 · library stats

## Safety Rules — MANDATORY

- **NEVER delete originals** — all scripts are read-only by default
- **NEVER permanently delete** — use Trash mode or move to review folder
- **Ask before moving** — ALWAYS present plan and get confirmation
- **Fast/Safe path** — 1-9 moves: `[Y/n]`; 10+ moves: require explicit `"yes"`
- **Undo available** — `--undo` reverses last operation (30-day expiry)
- **Shared albums are read-only** — Apple blocks all programmatic writes to shared albums

## Quick Start

```bash
pip install -r requirements.txt

# Step 1: See what albums exist in Photos Library
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary --list-albums

# Step 2: Clean duplicates in a specific album (keep originals = oldest)
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --album-filter "我的旅行" --strategy oldest --dry-run

# Step 3: Full interactive workflow
python3 scripts/organize_photos.py --source ~/Pictures/Export --interactive

# Step 4: Organize Photos.app into date-based albums
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by date

# Step 5: Organize by category (Screenshots, Photos, etc.)
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by category --dry-run

# Import from external drive into Photos.app
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --dry-run
```

## Strategy Choices — How to Decide Which Duplicate to Keep

| Strategy | Keeps | Best for |
|----------|-------|----------|
| `quality` (default) | Highest resolution + largest file + best EXIF | General cleanup — always keep the best version |
| `oldest` | Earliest capture date | Keep the original, remove later copies/edits |
| `newest` | Latest modification date | Keep the final edit, remove older versions |
| `folder` + `--prefer-folder DCIM` | Files from preferred folder | Keep camera originals, remove Backup/Download copies |
| `folder` + `--prefer-album "Favorites"` | Files from preferred album | Keep photos in your favorite album, remove duplicates elsewhere |

## Album-Aware Dedup — Clean Specific Albums

```bash
# List available albums first
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary --list-albums

# Only process duplicates within "旅行照片" album
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --album-filter "旅行照片" --dry-run

# Skip "Screenshots" album from dedup
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --exclude-album "Screenshots" --dry-run

# Prefer keeping photos from "Favorites" album
python3 scripts/generate_move_plan.py --duplicates dup.csv --index index.db \
  --plan plan.csv --target-root ~/review --strategy folder --prefer-album "Favorites"
```

## Process

1. **Scan** — `scan_photos.py` (folders) or `scan_photos_library.py` (Photos.app)
2. **Find duplicates** — `find_exact_duplicates.py` (SHA-256) or `find_similar_photos.py --detect-all` (8 modes)
3. **Preview** — `generate_preview.py` → HTML thumbnails with KEEP/MOVE badges
4. **Generate plan** — `generate_move_plan.py --strategy quality|oldest|newest|folder`
5. **Review & apply** — `apply_move_plan.py --mode move|trash|photos-trash` (undo via `--undo`)

## Photos.app Album Organization — Create Albums by Date/Category

Create albums directly in Photos.app (not just file-system folders):

```bash
# Organize by year/month
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by date

# Organize by year only
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by year

# Organize by category (📸 Photos, 📱 Screenshots, 🔄 Burst, 💬 WeChat)
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by category

# Organize by format (JPEG, HEIC, PNG)
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by format

# Smart: year + category (e.g., "2026/📸 Photos", "2026/📱 Screenshots")
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by smart

# Preview without making changes
python3 scripts/organize_photos.py --source ~/Pictures/Photos\ Library.photoslibrary \
  --mode photos-album --album-organize-by date --dry-run
```

| `--album-organize-by` | Album names | Best for |
|------------------------|-------------|----------|
| `date` | `2026/06 – June` | Timeline browsing |
| `year` | `2026` | Yearly overview |
| `category` | `📸 Photos`, `📱 Screenshots` | Quick filtering |
| `format` | `JPEG`, `HEIC` | Format management |
| `smart` | `2026/📸 Photos` | Combined timeline + category |

## HTML Report — Before/After Diff

After `--mode photos-album` or `--mode dedup`, an HTML report is automatically generated with:

- **Summary cards** — albums created, photos organized, errors
- **Before → After diff** — new albums, changed albums (photo count delta), unchanged albums
- **Library overview** — total photos, size, date range, format count
- **Category & format distribution** — bar charts
- **Album cards** — thumbnails, photo count, status badges (新建/已有/失败)

Report is saved to `{output_dir}/reports/album_report.html` and auto-opened in browser.

Works with `--dry-run` too — preview what *would* change before executing.

## Library Health & Insights — Read-Only Stats

Get an at-a-glance health report of any scanned library — **never modifies anything**:

```bash
# Terminal report (totals, category/format/year breakdown, health flags, top space hogs)
python3 scripts/library_stats.py --index photo_index.db

# Also write a self-contained HTML report
python3 scripts/library_stats.py -i photo_index.db --report health.html

# Machine-readable JSON (for piping into other tools)
python3 scripts/library_stats.py -i photo_index.db --format json

# Or via the orchestrator (scans first, then reports, auto-opens HTML)
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode stats
```

Surfaces: total items/size/date span · category & format & year distribution ·
health flags (screenshots, no-EXIF, GPS/privacy, iCloud-only, possibly-blurry
via Apple sharp score, favorites) · top-10 space consumers.

## Output Directory Structure

```
snaptidy_output/          # Default output (--output-dir)
├── scan/                 # Scan results
│   ├── photo_index.db    # SQLite metadata index
│   └── duplicates.csv    # Detected duplicate groups
├── plans/                # Move plans & manifests
│   ├── move_plan.csv     # Planned actions
│   └── plan_manifest.json
├── reports/              # HTML reports
│   ├── album_report.html # Album organization report
│   ├── library_health.html # Library health & insights (--mode stats)
│   └── preview.html      # Duplicate thumbnail preview
└── logs/                 # Execution logs
    └── move_log.csv      # Applied move log
```

## Shared Modules (internal)

Common logic lives in three importable modules (single source of truth — no duplication):

- `scripts/photo_metadata.py` — SHA-256, pHash, EXIF (datetime/GPS/camera/subsec), image size, aspect ratio + optional-dependency flags
- `scripts/constants.py` — extension sets, format-family mapping, Core Data epoch, month names, album-name maps, `format_size`
- `scripts/applescript_utils.py` — AppleScript string escaping + `osascript` invocation

## CLI Conventions

Flags are standardized across all scripts (old names kept as aliases):

- `--source` (`--input` / `--library`, `-i` for folders) — photo source
- `--index` (`-i`) — SQLite metadata index (consumed by dedup/report tools)
- `--output` (`-o`, also `--report` for HTML producers) — output path

## Photos.app "Recently Deleted" — Safe Cleanup

When using `--mode photos-trash`, deleted photos go to Photos.app's **"最近删除" / "Recently Deleted"** album (30-day recovery).

- **First use**: macOS will show an automation permission dialog — click "允许" / "Allow"
- **Permission denied?**: Go to 系统设置 > 隐私与安全性 > 自动化, enable Photos for your Terminal
- **Fallback**: If permission unavailable, a `.applescript` file is generated for manual execution

For detailed detection algorithms, priority rules, import workflow, iCloud integration, performance benchmarks, and troubleshooting, see `references/`.
