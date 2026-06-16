---
description: SnapTidy - macOS photo/video organizer skill rules
globs:
alwaysApply: true
---

# SnapTidy Project Rules

## Safety
- NEVER delete files — only move them
- NEVER enter .photoslibrary directories
- Always get user confirmation before applying move plans
- Log all file operations to CSV
- Scan writes commit each entry immediately — zero data loss on crash

## Code
- Python 3.9+, PEP 8
- CLI scripts use argparse with --input/--output/--index flags
- SQLite (.db) preferred; CSV as fallback
- CSV data exchange uses UTF-8 with BOM
- No heavy dependencies (no pandas/numpy)

## Pipeline
scan → dedup → plan → apply → (undo)
(read-only → read-only → read-only → move-only → reverse)

## Import
import_to_photos.py — import from external drives/Android into Photos.app with dedup
