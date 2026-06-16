# Import to Photos.app

Import photos from external drives or Android phones into macOS Photos.app, with automatic dedup against the existing library.

## Basic Import

```bash
# Dry-run: preview what would be imported
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --dry-run

# Import all unique photos (duplicates skipped)
python3 scripts/import_to_photos.py --source /Volumes/External/Photos

# Import into a specific album (auto-created if missing)
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --album "Vacation 2025"

# Import from Android DCIM
python3 scripts/import_to_photos.py --source /Volumes/Android/DCIM --album "Android Import"

# Resume a previously interrupted import
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --resume
```

## Import Workflow

1. **Scan source** - recursively find all media files
2. **Build library index** - read Photos.sqlite to build SHA-256 index
3. **Dedup** - compare source file SHA-256 against library; skip duplicates
4. **Import** - import unique files via photoscript / osascript / ScriptingBridge
5. **Report** - generate JSON report with import summary, duplicates found, and errors

## Import Methods

| Method | Flag | Dependencies | Speed | Notes |
|--------|------|-------------|-------|-------|
| Auto | `--method auto` | (picks best available) | - | Default |
| photoscript | `--method photoscript` | `pip install photoscript` | Medium | Most reliable |
| osascript | `--method osascript` | None (macOS built-in) | Slow | No extra deps |
| ScriptingBridge | `--method scriptingbridge` | `pip install pyobjc` | Medium | Low-level PyObjC |

## Shared Album Support

```bash
# List shared albums from Photos.sqlite
python3 scripts/import_to_photos.py --show-shared-albums
```

Reads shared album information from Photos.sqlite:
- Album title, owner name, ownership status
- Whether multiple contributors are enabled
- Public URL status
- Asset count

**Limitation**: Shared albums are **read-only** via all programmatic APIs (AppleScript, ScriptingBridge, PhotoKit, Shortcuts). Apple explicitly blocks adding photos to shared albums programmatically - `PHAssetCollection.canPerform(.addContent)` returns `false` for `.albumCloudShared`. This is an Apple design decision, not a bug.

To add photos to a shared album:
1. Import to a regular album first
2. Manually drag photos from the regular album to the shared album in Photos.app

## iCloud Considerations

- **Library index** only includes files that exist locally (iCloud-only files are skipped)
- **Storage check** warns if available disk space is < 5 GB (iCloud sync may fail)
- **Import report** includes total import size for storage planning
- After import, Photos.app will automatically sync to iCloud if enabled

## Import Report

Each import generates a JSON report:

```json
{
  "generated_at": "2025-06-15T15:00:00",
  "source_path": "/Volumes/External/Photos",
  "dry_run": false,
  "summary": {
    "total_source_files": 250,
    "unique_files": 180,
    "duplicate_files": 70,
    "imported": 180,
    "errors": 0
  },
  "duplicates": [...],
  "imported": [...],
  "errors": []
}
```

## iPhone Direct USB Management

iPhone users do NOT need iCloud sync to organize photos. Options:
- **Photos.app scan**: Connect iPhone via USB, scan the Photos Library directly
- **Finder sync**: Use Finder to sync photos to a local folder, then scan
- **pymobiledevice3**: Direct USB access to iPhone DCIM without iCloud
