#!/usr/bin/env python3
"""Reverse geocoding — convert GPS coordinates to place names.

Supports two backends:
  1. Nominatim (online, free, rate-limited to 1 req/s)
  2. macOS CoreLocation (offline, local, macOS only, no rate limit)

Results are cached in-memory so repeated coordinates within a single scan
are only looked up once.  A persistent JSON cache file can also be used
to speed up subsequent runs.

The module is intentionally optional — if neither backend is available,
all functions return empty strings and scanning proceeds without place data.
"""

import json
import os
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Persistent cache
# ---------------------------------------------------------------------------

_cache: dict = {}          # In-memory cache: "lat,lon" → place dict
_cache_path: str = ""      # Path to JSON cache file (set by init_cache)
_cache_dirty: bool = False # Whether we need to flush


def init_cache(cache_dir: str = "") -> None:
    """Initialise the geocode cache.  If *cache_dir* is given, a JSON file
    ``geocode_cache.json`` is created/loaded there for persistence across
    runs.  If empty, only the in-memory cache is used.
    """
    global _cache, _cache_path, _cache_dirty
    _cache_path = ""
    _cache_dirty = False

    if not cache_dir:
        return

    _cache_path = os.path.join(cache_dir, "geocode_cache.json")
    if os.path.exists(_cache_path):
        try:
            with open(_cache_path, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    else:
        _cache = {}
        os.makedirs(cache_dir, exist_ok=True)


def flush_cache() -> None:
    """Write the in-memory cache to disk (if a cache path was set)."""
    global _cache_dirty
    if not _cache_path or not _cache_dirty:
        return
    try:
        os.makedirs(os.path.dirname(_cache_path), exist_ok=True)
        with open(_cache_path, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
        _cache_dirty = False
    except Exception:
        pass


def _cache_key(lat, lon) -> str:
    """Round to ~111m precision (3 decimal places) for cache hits."""
    return f"{round(float(lat), 3)},{round(float(lon), 3)}"


# ---------------------------------------------------------------------------
# Backend: Nominatim (online)
# ---------------------------------------------------------------------------

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_last_nominatim_time: float = 0.0


def _nominatim_lookup(lat, lon, lang: str = "en") -> dict:
    """Query Nominatim reverse-geocoding API.  Returns place dict or {}."""
    global _last_nominatim_time

    # Rate limit: max 1 request per second (Nominatim policy)
    elapsed = time.time() - _last_nominatim_time
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        import urllib.request
        import urllib.parse

        params = urllib.parse.urlencode({
            "lat": lat,
            "lon": lon,
            "format": "json",
            "accept-language": lang,
            "zoom": 10,       # City/town level
            "addressdetails": 1,
        })
        url = f"{_NOMINATIM_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "snaptidy/3.8"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        _last_nominatim_time = time.time()
        return _parse_nominatim(data)
    except Exception:
        _last_nominatim_time = time.time()
        return {}


def _parse_nominatim(data: dict) -> dict:
    """Extract place fields from a Nominatim response."""
    addr = data.get("address", {})
    city = (addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("hamlet") or addr.get("municipality") or "")
    region = (addr.get("state") or addr.get("province")
              or addr.get("region") or "")
    country = addr.get("country", "")
    country_code = addr.get("country_code", "").upper()
    return {
        "place_city": city,
        "place_region": region,
        "place_country": country,
        "place_country_code": country_code,
    }


# ---------------------------------------------------------------------------
# Backend: macOS CoreLocation (offline, local)
# ---------------------------------------------------------------------------

_CORELOCATION_SCRIPT = r'''
import CoreLocation
import sys

lat, lon = float(sys.argv[1]), float(sys.argv[2])

manager = CoreLocation.CLLocationManager.alloc().init()
location = CoreLocation.CLLocation.alloc().initWithLatitude_longitude_(lat, lon)

# Use geocoder
geocoder = CoreLocation.CLGeocoder.alloc().init()

import threading
result = {}
event = threading.Event()

def completionHandler(placemarks, error):
    if not error and placemarks and len(placemarks) > 0:
        pm = placemarks[0]
        result['city'] = pm.locality() or ''
        result['region'] = pm.administrativeArea() or ''
        result['country'] = pm.country() or ''
        result['country_code'] = (pm.ISOcountryCode() or '').upper()
    event.set()

geocoder.reverseGeocodeLocation_completionHandler_(location, completionHandler)
event.wait(5.0)  # 5 second timeout

import json
print(json.dumps(result))
'''


def _corelocation_lookup(lat, lon) -> dict:
    """Use macOS CoreLocation framework for offline reverse geocoding.

    Requires macOS with PyObjC framework bridge (built into system Python).
    Falls back gracefully if unavailable.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CORELOCATION_SCRIPT, str(lat), str(lon)],
            capture_output=True, text=True, timeout=8,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            return {
                "place_city": data.get("city", ""),
                "place_region": data.get("region", ""),
                "place_country": data.get("country", ""),
                "place_country_code": data.get("country_code", ""),
            }
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Backend: macOS Locationator CLI (optional third-party)
# ---------------------------------------------------------------------------

def _locationator_lookup(lat, lon) -> dict:
    """Use the `locationator` CLI tool for offline reverse geocoding on macOS.

    locationator is a free macOS app that provides a local HTTP API for
    CoreLocation services.  See: https://github.com/sockeye44/locationator
    """
    try:
        import urllib.request
        # locationator runs a local server on port 8000
        url = f"http://localhost:8000/reverse?lat={lat}&lon={lon}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        addr = data.get("address", data)
        return {
            "place_city": addr.get("city", addr.get("locality", "")),
            "place_region": addr.get("state", addr.get("region", "")),
            "place_country": addr.get("country", ""),
            "place_country_code": addr.get("country_code", "").upper(),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Available backends in priority order
BACKENDS = {
    "corelocation": "macOS CoreLocation (offline, local)",
    "locationator": "Locationator HTTP API (offline, local)",
    "nominatim": "OpenStreetMap Nominatim (online, free)",
}

# Auto-detected backend (set on first call to reverse_geocode)
_active_backend: str = ""


def _detect_backend() -> str:
    """Auto-detect the best available backend."""
    # Try CoreLocation first (offline, fast)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import CoreLocation; print('ok')"],
            capture_output=True, text=True, timeout=3,
        )
        if proc.returncode == 0 and "ok" in proc.stdout:
            return "corelocation"
    except Exception:
        pass

    # Try Locationator
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8000/", timeout=1)
        return "locationator"
    except Exception:
        pass

    # Fall back to Nominatim (always available, but online)
    return "nominatim"


def reverse_geocode(lat, lon, backend: str = "", lang: str = "en") -> dict:
    """Convert GPS coordinates to place names.

    Returns dict with keys: place_city, place_region, place_country,
    place_country_code.  Empty strings on failure.

    Args:
        lat: Latitude (float or string)
        lon: Longitude (float or string)
        backend: "corelocation", "locationator", "nominatim", or "" (auto)
        lang: Language for place names (Nominatim only, default "en")
    """
    global _active_backend, _cache_dirty

    try:
        lat_f = float(lat)
        lon_f = float(lon)
        if lat_f == 0 and lon_f == 0:
            return _empty_place()
    except (ValueError, TypeError):
        return _empty_place()

    # Check cache
    key = _cache_key(lat_f, lon_f)
    if key in _cache:
        return _cache[key]

    # Detect backend on first call
    if not backend:
        if not _active_backend:
            _active_backend = _detect_backend()
        backend = _active_backend

    # Lookup
    result = _empty_place()
    if backend == "corelocation":
        result = _corelocation_lookup(lat_f, lon_f)
    elif backend == "locationator":
        result = _locationator_lookup(lat_f, lon_f)
    elif backend == "nominatim":
        result = _nominatim_lookup(lat_f, lon_f, lang=lang)

    # Validate result has at least one non-empty field
    if not any(result.values()):
        # Try fallback backends
        fallbacks = [b for b in ("corelocation", "locationator", "nominatim") if b != backend]
        for fb in fallbacks:
            if fb == "corelocation":
                result = _corelocation_lookup(lat_f, lon_f)
            elif fb == "locationator":
                result = _locationator_lookup(lat_f, lon_f)
            elif fb == "nominatim":
                result = _nominatim_lookup(lat_f, lon_f, lang=lang)
            if any(result.values()):
                break

    # Cache and return
    _cache[key] = result
    _cache_dirty = True
    return result


def _empty_place() -> dict:
    """Return an empty place dict (all fields blank)."""
    return {
        "place_city": "",
        "place_region": "",
        "place_country": "",
        "place_country_code": "",
    }


def batch_reverse_geocode(coords_list: list, backend: str = "",
                           lang: str = "en", progress_cb=None) -> list:
    """Reverse-geocode a list of (lat, lon) tuples.

    Returns a list of place dicts in the same order as input.
    Uses caching to avoid redundant lookups.

    Args:
        coords_list: List of (lat, lon) tuples
        backend: Backend name or "" (auto)
        lang: Language for place names
        progress_cb: Optional callback(current_index, total) for progress
    """
    results = []
    total = len(coords_list)
    for i, (lat, lon) in enumerate(coords_list):
        result = reverse_geocode(lat, lon, backend=backend, lang=lang)
        results.append(result)
        if progress_cb and (i % 10 == 0 or i == total - 1):
            progress_cb(i + 1, total)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Simple CLI for testing reverse geocoding."""
    parser = argparse.ArgumentParser(
        description="Reverse geocode GPS coordinates to place names")
    parser.add_argument("--lat", type=float, required=True,
                        help="Latitude")
    parser.add_argument("--lon", type=float, required=True,
                        help="Longitude")
    parser.add_argument("--backend", choices=list(BACKENDS.keys()), default="",
                        help="Geocoding backend (default: auto-detect)")
    parser.add_argument("--lang", default="en",
                        help="Language for place names (Nominatim only, default: en)")
    parser.add_argument("--cache-dir", default="",
                        help="Directory for persistent cache file")
    args = parser.parse_args()

    if args.cache_dir:
        init_cache(args.cache_dir)

    print(f"Reverse geocoding: ({args.lat}, {args.lon})")
    result = reverse_geocode(args.lat, args.lon, backend=args.backend, lang=args.lang)
    for k, v in result.items():
        print(f"  {k}: {v}")

    if args.cache_dir:
        flush_cache()


if __name__ == "__main__":
    import argparse
    main()
