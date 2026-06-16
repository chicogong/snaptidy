# Detection Methods

## Detection Types

| Type | Flag | Detects | Example |
|------|------|---------|---------|
| Exact (SHA-256) | `find_exact_duplicates.py` | Byte-identical files | Copies, synced duplicates |
| pHash | `--detect-phash` (default) | Identical/similar perceptual hash | Edits, crops |
| Scaled | `--detect-scaled` | Same photo at different resolutions | 4000x3000 vs 800x600 WeChat |
| Cross-format | `--detect-cross-format` | Same photo in different formats | iPhone HEIC + exported JPEG |
| Burst | `--detect-bursts` | Burst photos via SubSecTime | Multiple shots in same second |
| Apple QL | `--detect-apple-ql` | Similar via Apple ML quality vectors (zero-dep) | Visually similar photos |

## Scaled Duplicate Detection

Finds the same photo saved at different resolutions.

Algorithm:
1. Group images by aspect ratio (within 1.5% tolerance)
2. Check dimension ratio for simple scaling relationships (2x, 3x, 4x, etc.)
3. Verify with pHash similarity (Hamming distance <= 10)

## Cross-Format Duplicate Detection

Finds the same photo saved in different formats (e.g., iPhone HEIC original + JPEG export).

Algorithm:
1. Group images by aspect ratio
2. Within same group, find pairs with different format families
3. Check dimensions are within 0.5% (format conversion may crop 1px)
4. Verify with pHash similarity (Hamming distance <= 12)

## Burst Detection via SubSecTime

Groups burst photos taken within the same second using EXIF SubSecTimeOriginal.

Algorithm:
1. Extract sub-second timestamps from EXIF
2. Group photos by identical DateTimeOriginal
3. Photos with different SubSecTime in the same second are classified as burst

## Apple Quality Vector Detection (Zero-Dependency)

Uses Apple's pre-computed 17-dim ML feature vectors from `ZCOMPUTEDASSETATTRIBUTES` in Photos.sqlite. These vectors are computed by Apple's Vision framework when photos are imported into Photos.app.

**No external dependencies required** — uses only stdlib `math` for cosine similarity.

```bash
python3 scripts/find_similar_photos.py --index photo_index.db --output similar.csv --detect-apple-ql

# Adjust similarity threshold (default 0.92)
python3 scripts/find_similar_photos.py --index photo_index.db --output similar.csv --detect-apple-ql --apple-ql-threshold 0.95
```

The 17 quality scores include: composition, lighting, pattern, symmetry, color hue, sharpness, perspective, immersion, interaction, and more. Cosine similarity between these vectors identifies visually similar photos without needing Pillow or imagehash.

**Only available for Photos.app library scans** (`scan_photos_library.py` or `quick_scan.py --library`). File-system scans do not have access to Apple's pre-computed vectors.

## Quick Scan (Zero-Install)

`quick_scan.py` is a zero-dependency entry point that uses only Python stdlib:

```bash
# Scan a directory
python3 scripts/quick_scan.py --input /path/to/photos --output index.db --dedup

# Scan a Photos.app library (includes Apple QL vectors)
python3 scripts/quick_scan.py --library ~/Pictures/Photos\ Library.photoslibrary --output index.db --dedup
```

Capabilities: SHA-256 dedup, file size stats, auto-categorization (15+ languages), Apple QL vectors (library scan only).

Limitations vs. full scan: no pHash, no EXIF/GPS, no image dimensions (uses only stdlib).

## Human-Readable Output Format

Most output scripts support `--format human` for readable terminal reports:

```bash
python3 scripts/find_exact_duplicates.py --index index.db --output dups.txt --format human
python3 scripts/find_similar_photos.py --index index.db --output similar.txt --detect-all --format human
python3 scripts/generate_move_plan.py --duplicates dups.csv --index index.db --plan plan.txt --target-root /photos --format human
```
