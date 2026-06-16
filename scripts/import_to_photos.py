#!/usr/bin/env python3
"""Import photos from external sources into macOS Photos.app with dedup.

Workflow:
  1. Scan external source (hard drive, Android DCIM, or any folder)
  2. Build SHA-256 index of source files
  3. Cross-reference against existing Photos.app library (Photos.sqlite)
     to find duplicates before import
  4. Import unique photos into Photos.app via:
     - photoscript library (preferred, if installed)
     - osascript subprocess (fallback, no extra dependencies)
  5. Optionally import into a specific album (auto-created if missing)
  6. Generate import report with summary

SAFETY:
  - READ-ONLY on Photos.sqlite (never modifies it)
  - Only imports files that pass dedup check
  - --dry-run mode shows what WOULD be imported without actually importing
  - iCloud storage check warns if available space may be insufficient
  - Shared albums are READ-ONLY (cannot add photos via AppleScript)

LIMITATIONS:
  - Cannot import into shared albums (AppleScript/ScriptingBridge limitation)
  - Semi-automated workflow available: --share-to-album tags photos and opens
    Photos.app with them selected; user just drags to the shared album
  - Photos.app must be running for import operations
  - iCloud-synced library may have storage constraints
  - RAW files and Live Photos may need special handling
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta

# Optional: photoscript for high-level Photos.app control
try:
    import photoscript
    PHOTOSCRIPT_AVAILABLE = True
except ImportError:
    PHOTOSCRIPT_AVAILABLE = False

# Optional: PyObjC for low-level ScriptingBridge access
try:
    from ScriptingBridge import SBApplication
    from Foundation import NSURL
    PYOBJC_AVAILABLE = True
except ImportError:
    PYOBJC_AVAILABLE = False

# Core Data epoch: 2001-01-01 00:00:00 UTC
CORE_DATA_EPOCH = datetime(2001, 1, 1)

# Checkpoint file for resume support
CHECKPOINT_FILENAME = "import_checkpoint.json"

IMAGE_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff", "heic", "heif",
    "webp", "dng", "cr2", "nef", "arw",
}
VIDEO_EXTS = {
    "mov", "mp4", "m4v", "avi", "mkv", "3gp", "mpg", "mpeg",
    "hevc", "wmv", "flv",
}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

# Android / external drive DCIM patterns
ANDROID_PATTERNS = {"dcim", "camera", "100media", "100andro", "photo"}
ANDROID_MFR_DIRS = {
    "samsung", "galaxy", "pixel", "oneplus", "xiaomi", "huawei",
    "oppo", "vivo", "honor", "sony", "lg", "motorola", "htc",
}


def compute_sha256(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def detect_external_sources() -> list:
    """Detect mounted external drives and Android devices.

    Returns list of dicts with keys: path, type, label.
    """
    sources = []
    volumes_dir = "/Volumes"

    if not os.path.isdir(volumes_dir):
        return sources

    for name in os.listdir(volumes_dir):
        vol_path = os.path.join(volumes_dir, name)
        if not os.path.isdir(vol_path):
            continue

        # Check for Android DCIM
        dcim_path = os.path.join(vol_path, "DCIM")
        if os.path.isdir(dcim_path):
            # Determine if it's an Android phone
            is_android = False
            for subdir in os.listdir(dcim_path):
                sub_lower = subdir.lower()
                if sub_lower in ANDROID_PATTERNS or sub_lower in ANDROID_MFR_DIRS:
                    is_android = True
                    break

            sources.append({
                "path": dcim_path,
                "type": "android" if is_android else "camera_dcim",
                "label": f"{'Android' if is_android else 'Camera'} DCIM on {name}",
            })

        # Check for generic photo folders on external drives
        for folder_name in ("Photos", "Pictures", "photos", "pictures", "Import"):
            folder_path = os.path.join(vol_path, folder_name)
            if os.path.isdir(folder_path):
                sources.append({
                    "path": folder_path,
                    "type": "external_drive",
                    "label": f"{folder_name} on {name}",
                })
                break  # Only add one per volume

    return sources


def scan_source(source_path: str) -> list:
    """Scan external source and collect media files with metadata.

    Returns list of dicts: {file_path, filename, extension, size_bytes, sha256}.
    """
    files = []
    total = 0
    last_pct = -1

    # Phase 1: Collect file list (fast)
    file_list = []
    for root, dirs, fnames in os.walk(source_path):
        # Skip hidden and system directories
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]
        for name in fnames:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in MEDIA_EXTS:
                file_list.append((root, name, ext))

    total = len(file_list)
    print(f"  Found {total} media files in {source_path}")

    # Phase 2: Process each file with progress
    for idx, (root, name, ext) in enumerate(file_list):
        pct = idx * 100 // total if total > 0 else 100
        if pct >= last_pct + 10 or idx == 0:
            print(f"  Scanning... {idx}/{total} ({pct}%)")
            last_pct = pct

        file_path = os.path.join(root, name)
        try:
            size_bytes = os.path.getsize(file_path)
        except OSError:
            continue

        files.append({
            "file_path": file_path,
            "filename": name,
            "extension": ext,
            "size_bytes": size_bytes,
            "sha256": "",  # Computed later for dedup
        })

    print(f"  Scanned {len(files)} media files")
    return files


def build_library_index(library_path: str) -> dict:
    """Read Photos.sqlite and build SHA-256 → file_path index for dedup.

    Returns dict: {sha256_hex: [file_path, ...]}.
    """
    db_path = os.path.join(library_path, "database", "Photos.sqlite")
    if not os.path.exists(db_path):
        print(f"  ⚠️  Photos.sqlite not found at {db_path}", file=sys.stderr)
        print(f"     Please verify the library path.", file=sys.stderr)
        return {}

    index = defaultdict(list)
    originals_dir = os.path.join(library_path, "originals")

    # Work on a copy to avoid locking issues
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = tmp.name
    shutil.copy2(db_path, tmp_path)

    try:
        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row

        # Get all non-trashed assets with file paths
        cursor = conn.execute("""
            SELECT ZDIRECTORY, ZFILENAME, ZCLOUDLOCALSTATE
            FROM ZASSET
            WHERE ZTRASHEDSTATE = 0
        """)

        count = 0
        for row in cursor:
            directory = row["ZDIRECTORY"] or ""
            filename = row["ZFILENAME"] or ""
            cloud_state = row["ZCLOUDLOCALSTATE"] or 0

            if not directory or not filename:
                continue

            file_path = os.path.join(originals_dir, directory, filename)

            # Only index files that exist locally (not iCloud-only)
            if not os.path.exists(file_path):
                continue

            sha256 = compute_sha256(file_path)
            if sha256:
                index[sha256].append(file_path)
                count += 1

        conn.close()
    finally:
        os.unlink(tmp_path)

    print(f"  Library index: {count} files indexed from Photos.sqlite")
    return dict(index)


def get_shared_albums(library_path: str) -> list:
    """Read shared album information from Photos.sqlite.

    Returns list of dicts: {title, owner, is_owned, cloud_guid, asset_count}.
    """
    db_path = os.path.join(library_path, "database", "Photos.sqlite")
    if not os.path.exists(db_path):
        return []

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = tmp.name
    shutil.copy2(db_path, tmp_path)

    albums = []
    try:
        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row

        # Find junction table name dynamically (Z_XXASSETS pattern changes per macOS version)
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Z_%ASSETS'"
        ).fetchall()]
        junction_table = tables[0] if tables else None
        album_col = None
        asset_col = None

        if junction_table:
            # Determine column names
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({junction_table})").fetchall()]
            for col in cols:
                if "ALBUM" in col.upper():
                    album_col = col
                elif "ASSET" in col.upper():
                    asset_col = col

        # Get available columns from ZGENERICALBUM
        available_cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(ZGENERICALBUM)"
        ).fetchall()}

        # Build query with only available columns
        select_parts = ["Z_PK"]
        if "Z_ENT" in available_cols:
            select_parts.append("Z_ENT")
        col_map = {
            "ZTITLE": "ZTITLE",
            "ZKIND": "ZKIND",
            "ZISOWNED": "ZISOWNED",
            "ZCLOUDOWNERFULLNAME": "ZCLOUDOWNERFULLNAME",
            "ZCLOUDOWNERFIRSTNAME": "ZCLOUDOWNERFIRSTNAME",
            "ZCLOUDOWNERLASTNAME": "ZCLOUDOWNERLASTNAME",
            "ZCLOUDGUID": "ZCLOUDGUID",
            "ZCLOUDMULTIPLECONTRIBUTORSENABLED": "ZCLOUDMULTIPLECONTRIBUTORSENABLED",
            "ZCLOUDPUBLICURLENABLED": "ZCLOUDPUBLICURLENABLED",
            "ZCACHEDCOUNT": "ZCACHEDCOUNT",
            "ZPHOTOSCOUNT": "ZPHOTOSCOUNT",
            "ZVIDEOSCOUNT": "ZVIDEOSCOUNT",
            "ZCREATIONDATE": "ZCREATIONDATE",
        }
        for col, alias in col_map.items():
            if col in available_cols:
                select_parts.append(f"{col}")

        # Get Z_ENT for CloudSharedAlbum from Z_PRIMARYKEY
        shared_ent = None
        try:
            ent_cursor = conn.execute(
                "SELECT Z_PK FROM Z_PRIMARYKEY WHERE Z_ENTITYNAME = 'CloudSharedAlbum'"
            )
            row = ent_cursor.fetchone()
            if row:
                shared_ent = row[0]
        except sqlite3.OperationalError:
            pass

        # Build WHERE clause: prefer Z_ENT for CloudSharedAlbum if available,
        # otherwise use ZCLOUDOWNERFULLNAME IS NOT NULL as heuristic
        if shared_ent is not None:
            where_clause = f"Z_ENT = {shared_ent} AND ZTRASHEDSTATE = 0"
        elif "ZCLOUDOWNERFULLNAME" in available_cols:
            where_clause = "ZCLOUDOWNERFULLNAME IS NOT NULL AND ZTRASHEDSTATE = 0"
        else:
            where_clause = "ZCLOUDGUID IS NOT NULL AND ZTITLE IS NOT NULL AND ZTRASHEDSTATE = 0"

        query = f"SELECT {', '.join(select_parts)} FROM ZGENERICALBUM WHERE {where_clause}"

        cursor = conn.execute(query)

        for row in cursor:
            row_dict = dict(zip(select_parts, row))
            asset_count = row_dict.get("ZCACHEDCOUNT") or row_dict.get("ZPHOTOSCOUNT") or 0
            creation_date = ""
            if row_dict.get("ZCREATIONDATE"):
                try:
                    dt = CORE_DATA_EPOCH + timedelta(seconds=row_dict["ZCREATIONDATE"])
                    creation_date = dt.isoformat()
                except Exception:
                    pass

            albums.append({
                "title": row_dict.get("ZTITLE") or "Untitled",
                "owner": row_dict.get("ZCLOUDOWNERFULLNAME") or
                         f"{row_dict.get('ZCLOUDOWNERFIRSTNAME') or ''} {row_dict.get('ZCLOUDOWNERLASTNAME') or ''}".strip(),
                "is_owned": bool(row_dict.get("ZISOWNED")),
                "cloud_guid": row_dict.get("ZCLOUDGUID") or "",
                "multiple_contributors": bool(row_dict.get("ZCLOUDMULTIPLECONTRIBUTORSENABLED")),
                "public_url_enabled": bool(row_dict.get("ZCLOUDPUBLICURLENABLED")),
                "asset_count": asset_count,
                "creation_date": creation_date,
            })

        conn.close()
    finally:
        os.unlink(tmp_path)

    return albums


def get_icloud_storage_info() -> dict:
    """Estimate iCloud storage situation.

    Returns dict: {available_gb (estimated), warning (str or empty)}.
    """
    # Check disk space on the Photos Library volume as a proxy
    library_path = os.path.expanduser("~/Pictures/Photos Library.photoslibrary")
    if not os.path.exists(library_path):
        # Try to find the library
        pictures_dir = os.path.expanduser("~/Pictures")
        if os.path.isdir(pictures_dir):
            for item in os.listdir(pictures_dir):
                if item.endswith(".photoslibrary"):
                    library_path = os.path.join(pictures_dir, item)
                    break

    try:
        stat = os.statvfs(library_path)
        available_bytes = stat.f_frsize * stat.f_bavail
        available_gb = available_bytes / (1024 ** 3)
    except Exception:
        available_gb = -1

    warning = ""
    if available_gb >= 0 and available_gb < 5:
        warning = f"⚠️  Only {available_gb:.1f} GB available — iCloud sync may fail"

    return {"available_gb": round(available_gb, 1), "warning": warning}


def dedup_against_library(source_files: list, library_index: dict) -> tuple:
    """Compare source files against library index.

    Returns (unique_files, duplicate_files).
    """
    unique = []
    duplicate = []

    # Build SHA-256 for source files
    total = len(source_files)
    last_pct = -1
    print(f"  Computing SHA-256 for {total} source files...")

    for idx, f in enumerate(source_files):
        pct = idx * 100 // total if total > 0 else 100
        if pct >= last_pct + 10 or idx == 0:
            print(f"  Hashing... {idx}/{total} ({pct}%)")
            last_pct = pct

        sha256 = compute_sha256(f["file_path"])
        f["sha256"] = sha256

        if sha256 and sha256 in library_index:
            f["duplicate_of"] = library_index[sha256]
            duplicate.append(f)
        else:
            unique.append(f)

    print(f"  Dedup result: {len(unique)} unique, {len(duplicate)} duplicates")
    return unique, duplicate


def import_via_photoscript(file_paths: list, album_name: str = None,
                           skip_duplicates: bool = True) -> tuple:
    """Import files using the photoscript library.

    Returns (success_count, error_count, imported_paths, errors).
    """
    if not PHOTOSCRIPT_AVAILABLE:
        return 0, len(file_paths), [], ["photoscript not installed — pip install photoscript"]

    try:
        photoslib = photoscript.PhotosLibrary()
        photoslib.activate()

        album = None
        if album_name:
            album = photoslib.album(album_name, top_level=True)
            if album is None:
                album = photoslib.create_album(album_name)
                print(f"  Created album: {album_name}")

        # Import photos
        valid_paths = [f for f in file_paths if os.path.exists(f)]
        if not valid_paths:
            return 0, 0, [], ["No valid file paths to import"]

        if album:
            photoslib.import_photos(valid_paths, album=album,
                                    skip_duplicate=skip_duplicates)
        else:
            photoslib.import_photos(valid_paths, skip_duplicate=skip_duplicates)

        return len(valid_paths), 0, valid_paths, []

    except Exception as e:
        return 0, len(file_paths), [], [f"photoscript error: {e}"]


def import_via_osascript(file_paths: list, album_name: str = None,
                         skip_duplicates: bool = True) -> tuple:
    """Import files using osascript (AppleScript subprocess).

    Returns (success_count, error_count, imported_paths, errors).
    """
    success = 0
    errors = []
    imported = []

    for file_path in file_paths:
        if not os.path.exists(file_path):
            errors.append(f"File not found: {file_path}")
            continue

        # Build AppleScript
        if album_name:
            skip_str = "yes" if skip_duplicates else "no"
            script = f'''
            tell application "Photos"
                set targetAlbum to album "{album_name}"
                import POSIX file "{file_path}" into targetAlbum skip check duplicates {skip_str}
            end tell
            '''
        else:
            skip_str = "yes" if skip_duplicates else "no"
            script = f'''
            tell application "Photos"
                import POSIX file "{file_path}" skip check duplicates {skip_str}
            end tell
            '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                success += 1
                imported.append(file_path)
            else:
                errors.append(f"osascript error for {os.path.basename(file_path)}: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            errors.append(f"Timeout importing {os.path.basename(file_path)}")
        except Exception as e:
            errors.append(f"Error importing {os.path.basename(file_path)}: {e}")

    return success, len(file_paths) - success, imported, errors


def import_via_scriptingbridge(file_paths: list, album_name: str = None,
                               skip_duplicates: bool = True) -> tuple:
    """Import files using PyObjC ScriptingBridge directly.

    Returns (success_count, error_count, imported_paths, errors).
    """
    if not PYOBJC_AVAILABLE:
        return 0, len(file_paths), [], ["PyObjC not installed — pip install pyobjc"]

    try:
        photos = SBApplication.applicationWithBundleIdentifier_("com.apple.Photos")

        if photos is None:
            return 0, len(file_paths), [], ["Cannot connect to Photos.app"]

        # Find or create album
        target_album = None
        if album_name:
            albums = photos.albums()
            if albums:
                for album in albums():
                    try:
                        if album.name() == album_name:
                            target_album = album
                            break
                    except Exception:
                        continue

            if target_album is None:
                # Create album
                try:
                    target_album = photos.makeNew_atName_("album", album_name)
                    print(f"  Created album: {album_name}")
                except Exception as e:
                    return 0, len(file_paths), [], [f"Cannot create album: {e}"]

        success = 0
        imported = []
        errors = []

        for file_path in file_paths:
            file_url = NSURL.fileURLWithPath_(file_path)
            try:
                if target_album:
                    photos.import_into_skipCheckDuplicates_(
                        [file_url], target_album, skip_duplicates
                    )
                else:
                    photos.import_skipCheckDuplicates_(
                        [file_url], skip_duplicates
                    )
                success += 1
                imported.append(file_path)
            except Exception as e:
                errors.append(f"ScriptingBridge error for {os.path.basename(file_path)}: {e}")

        return success, len(file_paths) - success, imported, errors

    except Exception as e:
        return 0, len(file_paths), [], [f"ScriptingBridge error: {e}"]


def create_album_osascript(album_name: str) -> bool:
    """Create a new album in Photos.app via osascript."""
    script = f'''
    tell application "Photos"
        make new album named "{album_name}"
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False


def import_photos(source_path: str, library_path: str = None,
                  album_name: str = None, skip_duplicates: bool = True,
                  dry_run: bool = False, import_method: str = "auto",
                  report_path: str = None, resume: bool = False) -> None:
    """Main import workflow.

    Args:
        source_path: Path to external source (folder, DCIM, etc.)
        library_path: Path to .photoslibrary bundle (auto-detected if None)
        album_name: Target album name (created if missing)
        skip_duplicates: Skip files already in library
        dry_run: Show what would be imported without actually importing
        import_method: "auto", "photoscript", "osascript", or "scriptingbridge"
        report_path: Path to write import report JSON
        resume: Resume from previous interrupted import (skips already-imported files)
    """
    print(f"📦 SnapTidy Import — {source_path}")
    print()

    # Step 1: Auto-detect library path
    if library_path is None:
        pictures_dir = os.path.expanduser("~/Pictures")
        for item in os.listdir(pictures_dir):
            if item.endswith(".photoslibrary"):
                library_path = os.path.join(pictures_dir, item)
                break
        if library_path is None:
            print("❌ Cannot find Photos Library. Use --library to specify path.", file=sys.stderr)
            sys.exit(1)

    print(f"  Library: {library_path}")

    # Step 2: Check iCloud storage
    storage = get_icloud_storage_info()
    print(f"  Available disk space: {storage['available_gb']} GB")
    if storage["warning"]:
        print(f"  {storage['warning']}")

    # Step 3: Scan source
    print()
    print("Step 1: Scanning source...")
    source_files = scan_source(source_path)
    if not source_files:
        print("No media files found in source.")
        return

    # Step 4: Build library index for dedup
    print()
    print("Step 2: Building library index for dedup...")
    library_index = build_library_index(library_path)

    # Step 5: Dedup
    print()
    print("Step 3: Checking for duplicates...")
    unique_files, duplicate_files = dedup_against_library(source_files, library_index)

    if not unique_files:
        print()
        print("✅ All files already exist in Photos library — nothing to import.")
        if report_path:
            _write_report(report_path, source_path, source_files, unique_files,
                          duplicate_files, 0, 0, [], dry_run)
        return

    # Step 6: Calculate total import size
    total_size = sum(f["size_bytes"] for f in unique_files)
    total_size_mb = total_size / (1024 * 1024)
    print()
    print(f"Step 4: Import plan")
    print(f"  Files to import: {len(unique_files)}")
    print(f"  Duplicates skipped: {len(duplicate_files)}")
    print(f"  Total import size: {total_size_mb:.1f} MB")

    if album_name:
        print(f"  Target album: {album_name}")

    # Dry run — stop here
    if dry_run:
        print()
        print("🔍 DRY RUN — no files were imported.")
        print("  Use without --dry-run to actually import.")
        if report_path:
            _write_report(report_path, source_path, source_files, unique_files,
                          duplicate_files, 0, 0, [], dry_run=True)
        return

    # Step 7: Import
    print()
    print("Step 5: Importing...")

    import_paths = [f["file_path"] for f in unique_files]

    # Checkpoint support: resume from previous interrupted import
    checkpoint_path = os.path.join(
        os.path.dirname(os.path.abspath(report_path)) if report_path else os.path.dirname(source_path),
        CHECKPOINT_FILENAME
    )
    already_imported = set()
    if resume and os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, encoding="utf-8") as cf:
                ckpt = json.load(cf)
            already_imported = set(ckpt.get("imported_files", []))
            print(f"  📋 Resuming: {len(already_imported)} files already imported from previous run")
            # Filter out already-imported files
            import_paths = [p for p in import_paths if p not in already_imported]
            print(f"  Remaining: {len(import_paths)} files to import")
        except Exception as e:
            print(f"  ⚠️  Could not load checkpoint ({e}), starting fresh")

    # Choose import method
    if import_method == "auto":
        if PHOTOSCRIPT_AVAILABLE:
            import_method = "photoscript"
        elif PYOBJC_AVAILABLE:
            import_method = "scriptingbridge"
        else:
            import_method = "osascript"

    print(f"  Method: {import_method}")

    # Register signal handler for graceful shutdown — save checkpoint on Ctrl+C
    _checkpoint_ref = {"path": checkpoint_path, "imported": already_imported,
                        "source_path": source_path, "library_path": library_path}

    def _save_checkpoint_on_signal(signum, frame):
        """Save checkpoint on SIGINT/SIGTERM so user can resume later."""
        print(f"\n⚠️  Interrupted! Saving checkpoint...")
        try:
            ckpt_data = {
                "updated_at": datetime.now().isoformat(),
                "source_path": _checkpoint_ref["source_path"],
                "library_path": _checkpoint_ref["library_path"],
                "imported_files": sorted(_checkpoint_ref["imported"]),
                "total_imported": len(_checkpoint_ref["imported"]),
                "remaining": 0,  # Unknown at interrupt time
                "interrupted": True,
            }
            with open(_checkpoint_ref["path"], "w", encoding="utf-8") as cf:
                json.dump(ckpt_data, cf, indent=2, ensure_ascii=False)
            print(f"  Checkpoint saved: {_checkpoint_ref['path']}")
            print(f"  Use --resume to continue from where you left off.")
        except Exception as e:
            print(f"  ⚠️  Could not save checkpoint: {e}")
        sys.exit(130)

    signal.signal(signal.SIGINT, _save_checkpoint_on_signal)
    signal.signal(signal.SIGTERM, _save_checkpoint_on_signal)

    if import_method == "photoscript":
        success, errors, imported, error_msgs = import_via_photoscript(
            import_paths, album_name, skip_duplicates
        )
    elif import_method == "scriptingbridge":
        success, errors, imported, error_msgs = import_via_scriptingbridge(
            import_paths, album_name, skip_duplicates
        )
    else:
        success, errors, imported, error_msgs = import_via_osascript(
            import_paths, album_name, skip_duplicates
        )

    # Save checkpoint: record all successfully imported files for resume support
    all_imported = already_imported | set(imported)
    try:
        ckpt_data = {
            "updated_at": datetime.now().isoformat(),
            "source_path": source_path,
            "library_path": library_path,
            "imported_files": sorted(all_imported),
            "total_imported": len(all_imported),
            "remaining": len(import_paths) - success,
        }
        with open(checkpoint_path, "w", encoding="utf-8") as cf:
            json.dump(ckpt_data, cf, indent=2, ensure_ascii=False)
    except Exception:
        pass  # Checkpoint save failure is non-critical

    # Step 8: Report
    print()
    print("=" * 50)
    print(f"Import complete!")
    print(f"  ✅ Imported: {success}")
    print(f"  ⏭️  Duplicates skipped: {len(duplicate_files)}")
    print(f"  ❌ Errors: {errors}")
    if error_msgs:
        print(f"\n  Error details:")
        for msg in error_msgs[:10]:  # Show first 10 errors
            print(f"    - {msg}")
        if len(error_msgs) > 10:
            print(f"    ... and {len(error_msgs) - 10} more")

    # Write report
    if report_path:
        _write_report(report_path, source_path, source_files, unique_files,
                      duplicate_files, success, errors, error_msgs, dry_run=False)
        print(f"\n  Report: {report_path}")


def _write_report(report_path, source_path, source_files, unique_files,
                  duplicate_files, success_count, error_count,
                  error_msgs, dry_run=False):
    """Write import report as JSON."""
    report = {
        "generated_at": datetime.now().isoformat(),
        "source_path": source_path,
        "dry_run": dry_run,
        "summary": {
            "total_source_files": len(source_files),
            "unique_files": len(unique_files),
            "duplicate_files": len(duplicate_files),
            "imported": success_count if not dry_run else 0,
            "errors": error_count if not dry_run else 0,
        },
        "duplicates": [
            {
                "file_path": f["file_path"],
                "filename": f["filename"],
                "duplicate_of": f.get("duplicate_of", []),
            }
            for f in duplicate_files
        ],
        "imported": [
            {
                "file_path": f["file_path"],
                "filename": f["filename"],
                "size_bytes": f["size_bytes"],
            }
            for f in unique_files
        ] if not dry_run else [],
        "errors": error_msgs if not dry_run else [],
    }

    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def prepare_shared_album_workflow(album_name: str, keyword: str = "snaptidy-share") -> None:
    """Semi-automated workflow to add photos to a shared album.

    Since Apple blocks programmatic writes to shared albums, this function:
    1. Tags photos in the staging album with a keyword (AppleScript supports this)
    2. Opens Photos.app and selects those photos
    3. Prompts the user to drag them to the shared album (1 manual step)

    This reduces the workflow from ~10 steps to just 1 drag operation.
    """
    script = f'''
    tell application "Photos"
        activate
        set targetAlbum to album "{album_name}"
        set thePhotos to every media item of targetAlbum

        if (count of thePhotos) = 0 then
            display dialog "No photos found in album \\"{album_name}\\""
            return
        end if

        -- Add keyword for easy identification
        repeat with aPhoto in thePhotos
            set keywords of aPhoto to (keywords of aPhoto) & "{keyword}"
        end repeat

        -- Select all photos in the album
        set selection to thePhotos

        display dialog "✅ {len(thePhotos)} photos selected and tagged.\n\n" & ¬
            "Now DRAG the selected photos to your shared album in the sidebar.\n\n" & ¬
            "Tip: The shared album should be visible in the left sidebar under 'Shared'.\n" & ¬
            "The keyword '{keyword}' is added for future reference." with title "SnapTidy — Share to Shared Album" buttons {{"Done"}} default button 1
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"  ⚠️  AppleScript error: {result.stderr.strip()}", file=sys.stderr)
            print(f"     Make sure Photos.app is running and the album '{album_name}' exists.")
        else:
            print(f"  ✅ Photos tagged with '{keyword}' and selected in Photos.app")
            print(f"     👉 DRAG the selected photos to your shared album in the sidebar")
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  AppleScript timed out — is Photos.app responding?", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠️  Error: {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import photos from external sources into macOS Photos.app with dedup")
    parser.add_argument("--source",
                        help="Path to external source (folder, DCIM, drive mount point)")
    parser.add_argument("--library",
                        help="Path to .photoslibrary bundle (auto-detected if omitted)")
    parser.add_argument("--album",
                        help="Target album name in Photos.app (created if missing)")
    parser.add_argument("--skip-duplicates", action="store_true", default=True,
                        help="Skip files already in library (default: True)")
    parser.add_argument("--no-skip-duplicates", action="store_false", dest="skip_duplicates",
                        help="Import even if file appears to be a duplicate")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be imported without actually importing")
    parser.add_argument("--method", choices=["auto", "photoscript", "osascript", "scriptingbridge"],
                        default="auto",
                        help="Import method: auto (preferred available), photoscript, "
                             "osascript (no deps), scriptingbridge (PyObjC)")
    parser.add_argument("--report",
                        help="Path to write import report JSON")
    parser.add_argument("--resume", action="store_true",
                        help="Resume a previous interrupted import (skips already-imported files)")
    parser.add_argument("--detect-sources", action="store_true",
                        help="Detect mounted external drives and Android devices")
    parser.add_argument("--show-shared-albums", action="store_true",
                        help="List shared albums from Photos.sqlite (read-only)")
    parser.add_argument("--share-to-album",
                        help="Semi-automated: after importing to ALBUM, tag & select photos "
                             "in Photos.app so you can drag them to a shared album (1 manual step)")
    parser.add_argument("--share-keyword", default="snaptidy-share",
                        help="Keyword to tag photos with for shared album workflow (default: snaptidy-share)")
    args = parser.parse_args()

    # Detect external sources
    if args.detect_sources:
        print("🔍 Detecting external sources...")
        sources = detect_external_sources()
        if sources:
            print(f"\nFound {len(sources)} source(s):\n")
            for i, src in enumerate(sources, 1):
                print(f"  {i}. [{src['type']}] {src['label']}")
                print(f"     Path: {src['path']}")
        else:
            print("No external sources detected.")
            print("  Make sure your drive or Android phone is mounted.")
        return

    # Show shared albums
    if args.show_shared_albums:
        library_path = args.library
        if not library_path:
            pictures_dir = os.path.expanduser("~/Pictures")
            for item in os.listdir(pictures_dir):
                if item.endswith(".photoslibrary"):
                    library_path = os.path.join(pictures_dir, item)
                    break

        if not library_path or not os.path.exists(library_path):
            print("❌ Cannot find Photos Library. Use --library to specify path.", file=sys.stderr)
            sys.exit(1)

        print("📋 Shared Albums (read-only from Photos.sqlite)")
        print()
        albums = get_shared_albums(library_path)
        if albums:
            for i, album in enumerate(albums, 1):
                owned_str = "⭐ Owned" if album["is_owned"] else "📥 Subscribed"
                contrib_str = " | Multi-contributor" if album["multiple_contributors"] else ""
                print(f"  {i}. {album['title']}")
                print(f"     Owner: {album['owner']} | {owned_str}{contrib_str}")
                print(f"     Assets: {album['asset_count']} | GUID: {album['cloud_guid']}")
                if album["public_url_enabled"]:
                    print(f"     🔗 Public URL enabled")
                print()
            print(f"  ⚠️  Shared albums are READ-ONLY via AppleScript.")
            print(f"     To add photos, import to a regular album first,")
            print(f"     then manually drag to the shared album in Photos.app.")
        else:
            print("  No shared albums found.")
        return

    # Validate source path
    if not args.source:
        parser.error("--source is required for import (or use --detect-sources / --show-shared-albums)")

    source_path = os.path.abspath(args.source)
    if not os.path.isdir(source_path):
        print(f"❌ Source path does not exist: {source_path}", file=sys.stderr)
        sys.exit(1)

    # Import
    report_path = args.report
    if not report_path:
        report_path = os.path.join(os.path.dirname(source_path), "import_report.json")

    import_photos(
        source_path=source_path,
        library_path=args.library,
        album_name=args.album,
        skip_duplicates=args.skip_duplicates,
        dry_run=args.dry_run,
        import_method=args.method,
        report_path=report_path,
        resume=args.resume,
    )

    # Semi-automated shared album workflow
    if args.share_to_album and not args.dry_run:
        staging_album = args.share_to_album
        print()
        print("📋 Preparing shared album workflow...")
        prepare_shared_album_workflow(staging_album, keyword=args.share_keyword)


if __name__ == "__main__":
    main()
