# Storage & Performance

## Storage Formats

- **SQLite** (.db) - Recommended. Handles 100k+ photos efficiently. Query speed 400x faster than CSV for large libraries. Data stays local, no context bloat.
- **CSV** (.csv) - Fallback for small libraries. Compatible with Excel/Numbers.
- **HTML Preview** - Standalone HTML file with embedded thumbnails. Open in any browser.
- **Zero data loss** - Scan writes each entry to SQLite immediately with WAL mode + `synchronous=NORMAL`. A crash loses at most the entry currently being computed.

## Benchmarks (MacBook Pro M3 Pro)

| Photos | Scan | Exact | Similar (all) | Plan | Total |
|--------|------|-------|---------------|------|-------|
| 1K | 1.3s | 0.06s | 1.2s | 0.1s | ~3s |
| 10K | 12s | 0.07s | 49s | 0.3s | ~66s |
| 50K | 58s | 0.13s | ~8min | 0.5s | ~10min |

## Performance Tips for 10K+ Libraries

- Run `--detect-scaled` and `--detect-cross-format` separately instead of `--detect-all`
- Scan uses progress indicators (5% intervals) for large libraries
- pHash and exact detection are fast regardless of library size (indexed SQLite queries)
- Scaled detection is the bottleneck for 50K+ - consider running it overnight

## Supported Formats

| Type | Extensions |
|------|-----------|
| Images | jpg, jpeg, png, bmp, gif, tif, tiff, heic, heif, webp |
| RAW | dng, cr2, nef, arw |
| Videos | mov, mp4, m4v, avi, mkv, 3gp, mpg, mpeg, hevc, wmv, flv |
