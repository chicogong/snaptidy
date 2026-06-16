# SnapTidy

[English](README.md) | [简体中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/Platform-macOS-black.svg?style=flat-square)](https://www.apple.com/macos)
[![AI Skill](https://img.shields.io/badge/AI-Skill-purple.svg?style=flat-square)](https://github.com/topics/ai-skill)
[![Version](https://img.shields.io/badge/Version-3.3-green.svg?style=flat-square)](https://github.com/chicogong/snaptidy)

> AI-powered photo & video organizer for macOS. Deduplicate, tidy up, and restructure your library — safely, through conversation.

## Table of Contents

- [Why SnapTidy?](#why-snaptidy)
- [What's New](#whats-new-in-v33)
- [Key Features](#key-features)
- [Installation](#installation)
- [How It Works](#how-it-works)
- [Safety Guarantees](#safety-guarantees)
- [Quick Start](#quick-start)
- [Smart Priority Rules](#smart-priority-rules)
- [Auto-Categorization](#auto-categorization-15-languages)
- [Storage & Performance](#storage--performance)
- [Supported Formats](#supported-formats)
- [Scripts Reference](#scripts-reference)
- [Requirements](#requirements)
- [Platform Compatibility](#platform-compatibility)
- [Contributing](#contributing)
- [License](#license)

## Why SnapTidy?

Your photo library grows fast — iPhone shots, iCloud exports, Android transfers, WeChat saves, old backups, and screenshots pile up over time. Existing tools like [Sorty](https://github.com/nicoschmdt/sorty), [Tidy](https://github.com/nicoschmdt/tidy), and [Hazelnut](https://github.com/josephearl/hazelnut) are standalone apps you install and configure. **SnapTidy takes a different approach**: it's an AI assistant skill. You describe what you want in natural language, and it handles the rest.

The key difference? **Safety first, zero risk.** SnapTidy never deletes anything. It scans read-only, produces a human-readable plan, and only moves files after you explicitly approve — optionally to macOS Trash (recoverable via Finder).

## What's New in v3.3

| Feature | Description |
|---------|-------------|
| 📱 **Import to Photos.app** | Import from external drives/Android with automatic dedup |
| 👥 **Shared Album Reading** | Read shared album info from Photos.sqlite |
| ☁️ **iCloud Sync Awareness** | Detect iCloud-only files and download status |
| 🔄 **Checkpoint & Resume** | Import workflow supports checkpoint resume on interruption |
| 💾 **Zero Data Loss** | Streaming SQLite writes — commit each entry immediately |

<details>
<summary>Previous versions</summary>

| Version | Features |
|---------|----------|
| 🗄️ **v2.0** | SQLite storage (400x faster), smart priority rules, macOS Trash mode, GPS & camera metadata, auto-categorization |
| 🔍 **v3.0** | Scaled dedup, cross-format dedup (HEIC↔JPEG), burst detection, Photos.app scan, PyObjC deletion |
| 🖥️ **v3.1** | Interactive workflow, HTML preview with KEEP/MOVE badges, undo system, iCloud/Android/external drive detection, 15+ languages |
| 📅 **v3.2** | By-date (YYYY/MM) and by-category organize modes |

</details>

## Key Features

- 🎯 **SHA-256 Exact Dedup** — Find byte-perfect duplicate files across your entire library
- 👁️ **Perceptual Hash Similarity** — Detect visually identical images using pHash, with fuzzy Hamming distance threshold
- 🔀 **Cross-Format Dedup** — HEIC + JPEG of the same photo
- 📐 **Scaled Dedup** — Same photo at different resolutions
- 📸 **Burst Detection** — Group burst photos via SubSecTime
- 📋 **Rich Metadata Index** — Extract file size, EXIF dates, GPS, camera info, dimensions, category, hashes into SQLite or CSV
- 🛡️ **Safety-First Design** — Read-only scanning, move-only operations, Trash mode with Finder recovery, CSV-based audit trail
- 💾 **Zero Data Loss** — Streaming SQLite writes with per-entry commit
- 💬 **Conversation-Driven** — Interact through your AI assistant; no GUI or config files needed
- ⚡ **Zero Config** — Point at a directory and go
- 🔌 **Multi-Platform** — Works with Claude Code, Cursor, Windsurf, WorkBuddy, OpenClaw, and more
- 🗄️ **Scalable** — SQLite backend handles 100k+ photos

## Installation

### Option 1: One-Prompt Install (Recommended)

Just tell your AI assistant:

> Install this skill: https://github.com/chicogong/snaptidy

### Option 2: CLI Install

```bash
# Works with 45+ AI platforms
npx skills add chicogong/snaptidy

# Or via ClawHub
clawhub install snaptidy
```

### Option 3: Manual Install

<details>
<summary>Claude Code</summary>

```bash
git clone https://github.com/chicogong/snaptidy.git ~/.claude/skills/snaptidy
cd ~/.claude/skills/snaptidy && pip install -r requirements.txt
```
</details>

<details>
<summary>Cursor</summary>

```bash
git clone https://github.com/chicogong/snaptidy.git
cp -r snaptidy/.cursor/rules/snaptidy.mdc .cursor/rules/
```
</details>

<details>
<summary>WorkBuddy</summary>

```bash
git clone https://github.com/chicogong/snaptidy.git ~/.workbuddy/skills/snaptidy
cd ~/.workbuddy/skills/snaptidy && pip install -r requirements.txt
```
</details>

## How It Works

```
┌─────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  Scan   │────>│  Find Dupes  │────>│  Gen Plan    │────>│ Review & Apply│
│         │     │              │     │             │     │              │
│ Photos  │     │ SHA-256 +    │     │ Smart move  │     │ You confirm, │
│ & Videos│     │ pHash ±thr   │     │ plan (CSV)  │     │ then it moves │
└─────────┘     └──────────────┘     └─────────────┘     └──────────────┘
  Read-only        Read-only           Read-only          Move/Trash-only
```

1. **Scan** — Walk through your photo/video directory, extract metadata (size, SHA-256, EXIF date, GPS, camera info, dimensions, perceptual hash, auto-category, folder tag), and write to SQLite (recommended) or CSV
2. **Find Duplicates** — Group files by exact hash (SHA-256) and perceptual hash (pHash), with optional fuzzy threshold
3. **Generate Plan** — Smart multi-factor scoring decides which duplicate to keep. Supports configurable strategies and folder preferences
4. **Review & Apply** — Open the CSV plan, verify everything looks right, then apply. Choose between move-to-folder or macOS Trash (recoverable)

## Safety Guarantees

| Guarantee | How |
|-----------|-----|
| No automatic deletion | All scripts are read-only by default; `apply_move_plan.py` only moves files |
| macOS Trash mode | Use `--mode trash` to move to Trash — recoverable via Finder → Put Back |
| Human review required | Move plans are CSV files you can inspect in any spreadsheet app |
| Full audit trail | Every move is logged to `move_log.csv` with source, destination, status, and reason |
| Zero data loss | Streaming SQLite writes with per-entry commit — crash loses at most one entry |
| Skip existing files | If a destination file already exists, the move is skipped automatically |
| Photos Library protection | `.photoslibrary` and `.photolibrary` directories are never entered |
| Backup-aware | Directories named `Original_Backup`, `.trashes`, etc. are automatically skipped |
| Smart priorities | Multi-factor scoring ensures the best-quality photo is always kept |

## Quick Start

### Prerequisites

- **macOS** (tested on 13+)
- **Python 3.9+**
- **Full Disk Access** enabled for your terminal (System Settings → Privacy & Security → Full Disk Access)

### Usage

Tell your AI assistant what you want:

> *"Scan my photo library at /Volumes/Photos and find duplicates"*

Or run the scripts directly:

```bash
# Step 1: Scan (SQLite recommended for large libraries)
python3 scripts/scan_photos.py --input /path/to/your/photos --output ./photo_index.db

# Step 2: Find exact duplicates
python3 scripts/find_exact_duplicates.py --index ./photo_index.db --output ./duplicates_exact.csv

# Step 3 (Optional): Find perceptually similar images
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./duplicates_similar.csv
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --detect-all

# Step 4: Generate a smart move plan
python3 scripts/generate_move_plan.py \
    --duplicates ./duplicates_exact.csv \
    --index ./photo_index.db \
    --plan ./move_plan.csv \
    --target-root /path/to/your/photos \
    --prefer-folder "DCIM" --strategy quality

# Step 5: Preview with HTML thumbnails (optional but recommended)
python3 scripts/generate_preview.py \
    --duplicates ./duplicates_similar.csv \
    --index ./photo_index.db \
    --output ./preview.html

# Step 6: Review move_plan.csv, then apply
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --mode trash

# Step 7: Undo if needed
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --undo
```

### Import to Photos.app

```bash
# Dry-run: preview what would be imported
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --dry-run

# Import all unique photos (duplicates skipped automatically)
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --album "Vacation 2025"

# Import from Android DCIM
python3 scripts/import_to_photos.py --source /Volumes/Android/DCIM --album "Android Import"
```

### One-Command Interactive Workflow

```bash
# Interactive — asks preferences step by step
python3 scripts/organize_photos.py --source ~/Pictures/Export --interactive

# Non-interactive with dry-run
python3 scripts/organize_photos.py \
    --source ~/Pictures/Export --dedup-method all \
    --strategy quality --trash-mode trash --dry-run

# Organize by date into YYYY/MM folders
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-date --dry-run

# Organize by category (01_Photos, 02_Screenshots, 03_WeChat, etc.)
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-category --dry-run

# Detect connected Android devices and external drives
python3 scripts/organize_photos.py --source /any --detect-sources
```

## Smart Priority Rules

When deciding which duplicate to KEEP, SnapTidy scores files by:

| Factor | Weight | Rationale |
|--------|--------|-----------|
| Resolution (pixels) | High (0–100) | Higher res = better quality |
| File size | Medium (0–50) | Larger = less compressed |
| EXIF completeness | High (+30) | Has metadata = likely original |
| Format (RAW +20, HEIC +10) | Medium | Better format = better quality |
| Category (photo +15, screenshot -20, wechat -10) | Medium | Real photos over screenshots |
| Folder preference | Configurable (+50) | User-specified priority folders |
| Photos.app favorite | High (+50) | Never move favorited photos |

**Strategies** (`--strategy`): `quality` (default), `oldest`, `newest`, `folder`

## Auto-Categorization (15+ Languages)

| Category | Detected by |
|----------|------------|
| photo | Default for camera photos |
| screenshot | "screenshot", "截图", "截屏", "スクリーンショット", "스크린샷", "скриншот" |
| wechat | "mmexport", "wx_camera_", "microMsg", "WeiXin" |
| burst | "_HDR", "_burst", "连拍", "連拍", "버스트" |
| video | Video file extensions |

## Storage & Performance

| Format | Best For | Speed | Context Impact |
|--------|----------|-------|----------------|
| **SQLite** (.db) | 100k+ photos | 400x faster queries | Data stays in local DB, no context bloat |
| **CSV** (.csv) | Small libraries (<10k) | Fine for small sets | CSV content may bloat AI context |

### Benchmarks (MacBook Pro M3 Pro)

| Photos | Scan | Exact | Similar (all) | Plan | Total |
|--------|------|-------|---------------|------|-------|
| 1K | 1.3s | 0.06s | 1.2s | 0.1s | ~3s |
| 10K | 12s | 0.07s | 49s | 0.3s | ~66s |
| 50K | 58s | 0.13s | ~8min | 0.5s | ~10min |

## Supported Formats

| Type | Extensions |
|------|-----------|
| Images | jpg, jpeg, png, bmp, gif, tif, tiff, heic, heif, webp |
| RAW | dng, cr2, nef, arw |
| Videos | mov, mp4, m4v, avi, mkv, 3gp, mpg, mpeg, hevc, wmv, flv |

## Scripts Reference

| Script | Purpose | Input | Output |
|--------|---------|-------|--------|
| `scan_photos.py` | Walk directory, extract metadata + GPS + camera | Photo/video directory | `.db` or `.csv` |
| `scan_photos_library.py` | Scan Photos.app library (reads Photos.sqlite) | `.photoslibrary` bundle | `.db` or `.csv` |
| `find_exact_duplicates.py` | Group byte-identical files by SHA-256 | `.db` or `.csv` index | `duplicates_exact.csv` |
| `find_similar_photos.py` | Group visually identical images by pHash | `.db` or `.csv` index | `duplicates_similar.csv` |
| `generate_move_plan.py` | Smart priority scoring, propose which to move | Duplicates CSV + index | `move_plan.csv` |
| `apply_move_plan.py` | Execute move plan (move or Trash mode) + undo | `move_plan.csv` | `move_log.csv` |
| `organize_photos.py` | One-command interactive pipeline | Source directory | Full pipeline output |
| `import_to_photos.py` | Import to Photos.app with dedup | Source directory | Import report JSON |
| `generate_preview.py` | HTML thumbnail preview | Duplicates CSV + index | `preview.html` |

## Requirements

| Package | Purpose |
|---------|---------|
| **Pillow** | Image reading, dimensions, format conversion |
| **piexif** | EXIF data extraction (dates, GPS, camera info) |
| **imagehash** | Perceptual hash computation |

Only 3 core dependencies. No heavy frameworks. SQLite is built into Python.

Optional: **pillow-heif** (HEIC/HEIF support), **pyobjc-framework-Photos** (Photos.app deletion), **photoscript** (Photos.app import)

## Platform Compatibility

| Platform | Config File | Install Path |
|----------|------------|--------------|
| Claude Code | `CLAUDE.md` | `~/.claude/skills/snaptidy/` |
| Cursor | `.cursor/rules/snaptidy.mdc` | Project `.cursor/rules/` |
| Windsurf | `.windsurf/rules/snaptidy.md` | Project `.windsurf/rules/` |
| WorkBuddy | `SKILL.md` | `~/.workbuddy/skills/snaptidy/` |
| OpenClaw | `SKILL.md` + `clawhub.yaml` | `~/.openclaw/skills/snaptidy/` |
| Any AI agent | `AGENTS.md` | Project root |

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

Some areas where help is especially appreciated:

- **Date-based reorganization** — Sort photos into year/month folders based on EXIF dates
- **Video deduplication** — Key-frame hashing for video files using ffmpeg/opencv
- **Cross-platform support** — Extend beyond macOS to Linux and Windows
- **Location-based organize** — Reverse geocoding for GPS metadata

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a history of notable changes.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Inspired by the macOS automation community and tools like [organize](https://github.com/tfeldmann/organize), [FileLens](https://github.com/priyanshul/get-file-details), [Anthropic Skills](https://github.com/anthropics/skills), and the [Apple CLI](https://github.com/Sankalpcreat/Apple-CLI) ecosystem.
