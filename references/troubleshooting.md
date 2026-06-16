# Troubleshooting

| Problem | Solution |
|---------|----------|
| Permission denied | Enable Full Disk Access (System Settings > Privacy & Security > Full Disk Access) |
| No EXIF data | Screenshots and downloaded photos lack EXIF. Scan still works. |
| pHash false positives | Solid-color or very simple images produce identical pHash. Use SHA-256 as primary method, pHash as secondary. |
| HEIC not readable | Install `pillow-heif` (`pip install pillow-heif`) for full HEIC/HEIF support. |
| Photos.app scan fails | Ensure the .photoslibrary bundle is not being used by Photos.app at the same time. Close Photos.app first. |
| PyObjC deletion fails | Ensure `pyobjc-framework-Photos` is installed and Photos.app is running. |
| Large library slow scan | Use SQLite output (not CSV). Index is stored locally between runs. |
| External drive | Scan directly from the external drive path. Use `--prefer-folder` for the drive's photo folder. |
| Undo expired | Undo records expire after 30 days. Check `undo_records/` for existing records. |
| iCloud files skipped | iCloud-only files (not downloaded locally) are skipped during move. Use `--check-icloud` to detect them, or download via `brctl download`. |
| Android not detected | Ensure Android File Transfer is installed and the phone is unlocked. Check `/Volumes/` for mount points. |
| Import fails - Photos.app not running | Import requires Photos.app to be running. Launch Photos.app first, or the script will attempt to activate it. |
| Import method unavailable | If `photoscript` is not installed, the script falls back to `osascript`. Install with `pip install photoscript` for the best experience. |
| Shared albums not appearing | Shared albums are detected via `Z_ENT = CloudSharedAlbum` in Photos.sqlite. If no shared albums exist, the list will be empty. |
| Import duplicates | Use `--skip-duplicates` (default) to avoid importing files already in the library. Use `--no-skip-duplicates` to force import. |
| Cannot add to shared album | Apple blocks programmatic writes to shared albums via ALL APIs (AppleScript, PhotoKit, Shortcuts). Import to a regular album first, then manually drag to shared album in Photos.app. |
