# GitHub Copilot Instructions — SnapTidy

## Project Context
SnapTidy is a macOS photo/video organizer AI skill. It scans libraries, detects duplicates, and generates safe move plans. It never deletes files.

## Key Rules
- Safety first: never implement file deletion, only move operations
- All data flows through CSV files (scan → dedup → plan → apply)
- Scripts use argparse with `--input`/`--output`/`--index` style flags
- Python 3.9+, PEP 8, no heavy dependencies beyond Pillow/piexif/imagehash
- Always require user confirmation before any file move operation
- Log all operations to CSV audit trail
