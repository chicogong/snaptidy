# SnapTidy

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/Platform-macOS-black.svg)](https://www.apple.com/macos)
[![AI Skill](https://img.shields.io/badge/AI-Skill-purple.svg)](https://github.com/topics/ai-skill)
[![Version](https://img.shields.io/badge/Version-2.0-green.svg)](https://github.com/chicogong/snaptidy)

> AI-powered photo & video organizer for macOS. Deduplicate, tidy up, and restructure your library — safely, through conversation.
>
> 🇨🇳 整理照片去重 · 🇯🇵 重複写真整理 · 🇰🇷 중복 사진 정리 · 🇷🇺 Удаление дубликатов

## Why SnapTidy?

Your photo library grows fast — iPhone shots, iCloud exports, Android transfers, WeChat saves, old backups, and screenshots pile up over time. Existing tools like [Sorty](https://github.com/nicoschmdt/sorty), [Tidy](https://github.com/nicoschmdt/tidy), and [Hazelnut](https://github.com/josephearl/hazelnut) are standalone apps you install and configure. **SnapTidy takes a different approach**: it's an AI assistant skill. You describe what you want in natural language, and it handles the rest.

The key difference? **Safety first, zero risk.** SnapTidy never deletes anything. It scans read-only, produces a human-readable plan, and only moves files after you explicitly approve — optionally to macOS Trash (recoverable via Finder).

## What's New in v2.0

| Feature | Description |
|---------|-------------|
| 🗄️ **SQLite Storage** | 400x faster than CSV for 100k+ photos. Data stays local, no context bloat |
| 🎯 **Smart Priority Rules** | Multi-factor scoring: resolution, EXIF completeness, format, category, folder preference |
| 🗑️ **macOS Trash Mode** | Move duplicates to Trash (recoverable via Finder → Put Back) instead of review folder |
| 📍 **GPS & Camera Metadata** | Extract latitude/longitude, camera make/model, EXIF completeness |
| 🏷️ **Auto-Categorization** | Detect photo, screenshot, WeChat, burst, and video categories automatically |
| 🔍 **Fuzzy pHash Matching** | `--threshold` parameter for Hamming distance near-duplicate detection |
| 📂 **Folder Priority** | `--prefer-folder` lets you specify which folders' photos to keep |
| 📱 **Android/WeChat Support** | Detects `mmexport`, `wx_camera_`, `microMsg` filename patterns |
| 🌐 **Multilingual Detection** | Screenshots detected in Chinese, Japanese, Korean, Russian, and English |

## Key Features

- 🎯 **SHA-256 Exact Dedup** — Find byte-perfect duplicate files across your entire library
- 👁️ **Perceptual Hash Similarity** — Detect visually identical images using average hash (pHash), with fuzzy Hamming distance threshold
- 📋 **Rich Metadata Index** — Extract file size, EXIF dates, GPS coordinates, camera info, dimensions, category, and hashes into SQLite or CSV
- 🛡️ **Safety-First Design** — Read-only scanning, move-only operations, Trash mode with Finder recovery, CSV-based audit trail
- 💬 **Conversation-Driven** — Interact through your AI assistant; no GUI or config files needed
- ⚡ **Zero Config** — Point at a directory and go. Works with any macOS photo/video folder
- 🔌 **Multi-Platform** — Works with Claude Code, Cursor, Windsurf, WorkBuddy, OpenClaw, and more
- 🗄️ **Scalable** — SQLite backend handles 100k+ photos without breaking a sweat

## Installation

### Option 1: One-Prompt Install (Recommended)

Just tell your AI assistant:

> Install this skill: https://github.com/chicogong/snaptidy

The AI will automatically clone the repo, install dependencies, and configure the skill.

### Option 2: CLI Install

```bash
# Works with 45+ AI platforms (Claude Code, Cursor, Windsurf, etc.)
npx skills add chicogong/snaptidy

# Or via ClawHub (OpenClaw ecosystem)
clawhub install snaptidy

# Or via SkillHub (Tencent ecosystem)
skillhub install snaptidy
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
<summary>Windsurf</summary>

```bash
git clone https://github.com/chicogong/snaptidy.git
cp -r snaptidy/.windsurf/rules/snaptidy.md .windsurf/rules/
```
</details>

<details>
<summary>WorkBuddy</summary>

```bash
git clone https://github.com/chicogong/snaptidy.git ~/.workbuddy/skills/snaptidy
cd ~/.workbuddy/skills/snaptidy && pip install -r requirements.txt
```
</details>

<details>
<summary>GitHub Copilot</summary>

Copy `.github/copilot-instructions.md` to your project's `.github/` directory.
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
| Skip existing files | If a destination file already exists, the move is skipped automatically |
| Photos Library protection | `.photoslibrary` and `.photolibrary` directories are never entered |
| Backup-aware | Directories named `Original_Backup`, `.trashes`, etc. are automatically skipped |
| Smart priorities | Multi-factor scoring ensures the best-quality photo is always kept |

> See [`references/safety.md`](references/safety.md) for detailed safety guidelines.

## Quick Start

### Prerequisites

- **macOS** (tested on macOS 13+)
- **Python 3.9+**
- **Full Disk Access** enabled for your terminal (System Settings → Privacy & Security → Full Disk Access)

### Usage

Tell your AI assistant what you want:

> *"Scan my photo library at /Volumes/Photos and find duplicates"*

Or run the scripts directly:

```bash
# Step 1: Scan your photo library (SQLite recommended for large libraries)
python3 scripts/scan_photos.py \
    --input /path/to/your/photos \
    --output ./photo_index.db

# Step 2: Find exact duplicates
python3 scripts/find_exact_duplicates.py \
    --index ./photo_index.db \
    --output ./duplicates_exact.csv

# Step 3 (Optional): Find perceptually similar images
# Exact pHash match (default)
python3 scripts/find_similar_photos.py \
    --index ./photo_index.db \
    --output ./duplicates_similar.csv

# Fuzzy match with Hamming distance threshold (catches near-duplicates)
python3 scripts/find_similar_photos.py \
    --index ./photo_index.db \
    --output ./duplicates_similar.csv \
    --threshold 5

# Step 4: Generate a smart move plan
# Default: quality strategy — keep highest resolution, best EXIF, largest file
python3 scripts/generate_move_plan.py \
    --duplicates ./duplicates_exact.csv \
    --index ./photo_index.db \
    --plan ./move_plan.csv \
    --target-root /path/to/your/photos

# Keep files from preferred folders (e.g., camera originals over downloads)
python3 scripts/generate_move_plan.py \
    --duplicates ./duplicates_exact.csv \
    --index ./photo_index.db \
    --plan ./move_plan.csv \
    --target-root /path/to/your/photos \
    --prefer-folder "DCIM" --prefer-folder "相机"

# Choose a strategy: quality (default), oldest, newest, folder
python3 scripts/generate_move_plan.py \
    --duplicates ./duplicates_exact.csv \
    --index ./photo_index.db \
    --plan ./move_plan.csv \
    --target-root /path/to/your/photos \
    --strategy oldest

# Step 5: Review move_plan.csv, then apply
# Move to review folder (safe, files stay on disk)
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --mode move

# Move to macOS Trash (recoverable via Finder → Put Back)
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --mode trash
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

**Strategies** (`--strategy`):

| Strategy | Behavior |
|----------|----------|
| `quality` (default) | Keep the highest-scoring file based on multi-factor scoring |
| `oldest` | Keep the oldest file (by EXIF date, then mtime) |
| `newest` | Keep the newest file |
| `folder` | Keep the file from the highest-priority folder (`--prefer-folder` order) |

## Auto-Categorization

| Category | Detected by |
|----------|------------|
| photo | Default for camera photos |
| screenshot | "screenshot", "截图", "截屏", "スクリーンショット", "스크린샷", "скриншот" |
| wechat | "mmexport", "wx_camera_", "microMsg", "WeiXin" |
| burst | "_HDR", "_burst", "连拍" |
| video | Video file extensions |

## Storage & Performance

| Format | Best For | Speed | Context Impact |
|--------|----------|-------|----------------|
| **SQLite** (.db) | 100k+ photos | 400x faster queries | Data stays in local DB, no context bloat |
| **CSV** (.csv) | Small libraries (<10k) | Fine for small sets | CSV content may bloat AI context |

SQLite is strongly recommended for any real photo library. It stores all metadata locally in a single `.db` file, and queries use indexes for instant lookups. CSV is available as a fallback.

## Supported Formats

| Type | Extensions |
|------|-----------|
| Images | jpg, jpeg, png, bmp, gif, tif, tiff, heic, heif, webp |
| RAW | dng, cr2, nef, arw |
| Videos | mov, mp4, m4v, avi, mkv, 3gp, mpg, mpeg, hevc, wmv, flv |

## Scripts Reference

| Script | Purpose | Input | Output |
|--------|---------|-------|--------|
| `scan_photos.py` | Walk directory, extract metadata + GPS + camera info | Photo/video directory | `.db` (SQLite) or `.csv` |
| `find_exact_duplicates.py` | Group byte-identical files by SHA-256 | `.db` or `.csv` index | `duplicates_exact.csv` |
| `find_similar_photos.py` | Group visually identical images by pHash | `.db` or `.csv` index | `duplicates_similar.csv` |
| `generate_move_plan.py` | Smart priority scoring, propose which to move | Duplicates CSV + index | `move_plan.csv` |
| `apply_move_plan.py` | Execute move plan (move or Trash mode) | `move_plan.csv` | `move_log.csv` |

## Requirements

| Package | Purpose |
|---------|---------|
| **Pillow** | Image reading, dimensions, format conversion |
| **piexif** | EXIF data extraction (dates, GPS, camera info) |
| **imagehash** | Perceptual hash computation (average hash) |

Only 3 dependencies. No heavy frameworks. SQLite is built into Python.

## Language Support

SnapTidy handles filenames and paths in **CJK languages** (Chinese, Japanese, Korean) and other Unicode scripts natively. All CSV output uses UTF-8 with BOM for proper display in Excel and Numbers.

Screenshot detection works across languages:

| Language | Detected patterns |
|----------|-------------------|
| English | `screenshot`, `screen shot` |
| Chinese | `截图`, `截屏` |
| Japanese | `スクリーンショット` |
| Korean | `스크린샷` |
| Russian | `скриншот` |

WeChat image detection:

| Pattern | Source |
|---------|--------|
| `mmexport` | WeChat exported photos |
| `wx_camera_` | WeChat in-app camera |
| `microMsg` | WeChat internal storage |
| `WeiXin` | WeChat folder name |

## Platform Compatibility

| Platform | Config File | Install Path |
|----------|------------|--------------|
| Claude Code | `CLAUDE.md` | `~/.claude/skills/snaptidy/` |
| Cursor | `.cursor/rules/snaptidy.mdc` | Project `.cursor/rules/` |
| Windsurf | `.windsurf/rules/snaptidy.md` | Project `.windsurf/rules/` |
| GitHub Copilot | `.github/copilot-instructions.md` | Project `.github/` |
| WorkBuddy | `SKILL.md` | `~/.workbuddy/skills/snaptidy/` |
| OpenClaw | `SKILL.md` + `clawhub.yaml` | `~/.openclaw/skills/snaptidy/` |
| Any AI agent | `AGENTS.md` | Project root |

## Contributing

Contributions are welcome! Some areas where help is especially appreciated:

- **Date-based reorganization** — Sort photos into year/month folders based on EXIF dates
- **Video deduplication** — Key-frame hashing for video files using ffmpeg/opencv
- **iCloud integration** — Smart detection of iCloud-evicted files
- **Cross-platform support** — Extend beyond macOS to Linux and Windows
- **External drive workflows** — Backup-to-drive and space management automation

Feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Inspired by the macOS automation community and tools like [organize](https://github.com/tfeldmann/organize), [FileLens](https://github.com/priyanshul/get-file-details), [Anthropic Skills](https://github.com/anthropics/skills), and the [Apple CLI](https://github.com/Sankalpcreat/Apple-CLI) ecosystem.
