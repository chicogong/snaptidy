# GitHub Copilot Instructions — SnapTidy

## Project Context
SnapTidy is a macOS photo/video organizer AI skill. It scans libraries, detects duplicates (SHA-256 exact + pHash perceptual + scaled + cross-format + burst), generates safe move plans, and supports undo. It never deletes files.

## Key Rules
- Safety first: never implement file deletion, only move operations
- Data flows through SQLite (.db, preferred) or CSV — scan → dedup → plan → apply
- Scripts use argparse with `--input`/`--output`/`--index` style flags
- Python 3.9+, PEP 8, no heavy dependencies beyond Pillow/piexif/imagehash
- Always require user confirmation before any file move operation
- Log all operations to CSV audit trail
- Scan writes commit each entry immediately — zero data loss on crash
- For Photos.app libraries, use `scan_photos_library.py` (not `scan_photos.py`)
