# AGENTS.md — SnapTidy Project Rules

This file provides universal AI coding rules for the SnapTidy project. Compatible with Claude Code, Cursor, GitHub Copilot, Windsurf, and other AI coding agents.

## Project Overview

SnapTidy is a macOS photo/video organizer AI skill. It scans photo libraries, detects duplicates (SHA-256 exact + pHash perceptual), and generates safe move plans. It never deletes files.

## Code Conventions

- **Language**: Python 3.9+
- **Style**: PEP 8, 4-space indent, max line length 120
- **Scripts**: All scripts under `scripts/` are CLI tools using `argparse`
- **Input/Output**: All data exchange via CSV files (no databases)
- **Encoding**: All CSV files use UTF-8 with BOM for Excel compatibility

## Safety Constraints

- NEVER implement file deletion functionality
- NEVER modify files inside `.photoslibrary` or `.photolibrary` packages
- All file operations must be read-only by default
- Move operations require an explicit user confirmation step
- Always log operations to a CSV audit trail

## Architecture

```
Pipeline: Scan → Dedup → Plan → Apply
          (read)  (read)  (read)  (move-only)
```

Each step is independent and produces a CSV for the next step. This design allows:
- Running any step independently
- Manual review between steps
- Re-running from any point without data loss

## Dependencies

- Pillow: Image reading and metadata
- piexif: EXIF data extraction
- imagehash: Perceptual hash computation

Do NOT add pandas, numpy, or other heavy dependencies unless absolutely necessary.
