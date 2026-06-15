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

## Code
- Python 3.9+, PEP 8
- CLI scripts use argparse with --input/--output flags
- CSV data exchange (UTF-8 BOM)

## Pipeline
scan → dedup → plan → apply (read-only → read-only → read-only → move-only)
