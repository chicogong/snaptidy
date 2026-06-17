# Reverse Geocoding & By-Location Organize

## Overview

SnapTidy converts GPS coordinates (latitude/longitude) to human-readable place names (city, region, country) using reverse geocoding. This enables organizing photos by location — `Country/Region/City/filename`.

## Backends (Auto-Detected)

| Backend | Type | Speed | Requirements |
|---------|------|-------|-------------|
| CoreLocation | Offline (macOS) | Fastest | macOS + CoreLocation framework |
| Locationator | Local HTTP (macOS) | Fast | Locationator app running |
| Nominatim | Online (REST) | Slow (rate-limited) | Internet access |

Auto-detection priority: CoreLocation → Locationator → Nominatim.

## Persistent Cache

- **File**: `geocode_cache.json` (alongside the output DB)
- **Key**: Rounded lat/lon to 3 decimal places (~111m precision)
- **Behavior**: Cache is loaded on first geocode call, persisted on `flush_cache()` or at scan end
- **Cross-run**: Same cache file is reused across multiple scans, avoiding redundant API calls

## Scan Integration

`scan_photos.py` and `scan_photos_library.py` automatically perform reverse geocoding when GPS data is present:

```
scan_photos.py --source ~/Photos --output index.db          # geocoding ON (default)
scan_photos.py --source ~/Photos --output index.db --no-geocode  # geocoding OFF
```

New SQLite columns populated:
- `place_city` — e.g., "San Francisco", "Beijing"
- `place_region` — e.g., "California", "Beijing"
- `place_country` — e.g., "United States", "China"
- `place_country_code` — e.g., "US", "CN"

## By-Location Organize

```bash
python3 scripts/organize_photos.py --source ~/Photos --mode by-location --dry-run
```

### Folder Structure

When place data is available:
```
Country/Region/City/filename
  China/Beijing/Dongcheng/IMG_0001.jpg
  United States/California/San Francisco/IMG_0002.jpg
```

When no place data (GPS fallback):
```
GPS_N35_E139/filename
  GPS_N39_E116/IMG_0003.jpg
```

When no GPS data at all:
```
Unknown_Location/filename
```

### Prerequisites

- Scan index must have `place_city` column (i.e., scanned with geocoding enabled)
- If no place data is found, the mode will suggest re-scanning with `--geocode`

## CLI (reverse_geocode.py)

```bash
# Single coordinate lookup
python3 scripts/reverse_geocode.py --lat 39.9042 --lon 116.4074

# Specify backend
python3 scripts/reverse_geocode.py --lat 37.7749 --lon -122.4194 --backend nominatim

# Language preference
python3 scripts/reverse_geocode.py --lat 31.2304 --lon 121.4737 --lang en

# Custom cache directory
python3 scripts/reverse_geocode.py --lat 48.8566 --lon 2.3522 --cache-dir ./geocache
```

## Library Stats — Location Breakdown

`library_stats.py` now includes a `by_location` section showing the top cities by photo count:

```bash
python3 scripts/library_stats.py --index index.db                    # terminal output
python3 scripts/library_stats.py --index index.db --format json      # JSON output
python3 scripts/library_stats.py --index index.db --report health.html  # HTML report
```

Terminal output shows top 15 cities. HTML report includes a dedicated "By Location" card section with purple theme.
