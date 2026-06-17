#!/usr/bin/env python3
"""Library health & insights — read-only statistics over a scanned index.

Competitors (e.g. macos-media-scanner) surface "library health insights" as a
first-class command.  SnapTidy already stores everything needed for it, so
this script turns the existing index into an at-a-glance health report:

  * Totals: photo/video counts, total size, date span
  * Category breakdown (photo / screenshot / wechat / burst / video)
  * Format breakdown (jpeg / heic / png / raw / ...)
  * Top space consumers (largest files)
  * Photos-by-year timeline
  * Health flags: screenshots, possible blur (low Apple sharp score),
    no-EXIF files, iCloud-only files, files with GPS (privacy hint)

This is strictly READ-ONLY — it never moves, renames or deletes anything.

Usage:
    python3 scripts/library_stats.py --index photo_index.db
    python3 scripts/library_stats.py -i photo_index.db --report health.html
    python3 scripts/library_stats.py -i photo_index.db --format json
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict

from constants import format_size, MONTH_NAMES


# Apple's per-photo sharpness score lives in the quality vector; a low value
# is a reasonable "possibly blurry" heuristic when present.
SHARP_SCORE_KEY = "ZPLEASANTSHARPSCORE"
BLUR_THRESHOLD = 0.30


def _table_columns(conn) -> set:
    return {r[1] for r in conn.execute("PRAGMA table_info(photos)")}


def collect_stats(index_path: str) -> dict:
    """Gather read-only statistics from a scanned index.  Returns a dict."""
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    cols = _table_columns(conn)

    stats = {
        "index_path": os.path.abspath(index_path),
        "total": 0,
        "images": 0,
        "videos": 0,
        "total_bytes": 0,
        "date_min": "",
        "date_max": "",
        "by_category": {},
        "by_format": {},
        "by_year": {},
        "by_location": {},
        "largest": [],
        "flags": {},
    }

    rows = list(conn.execute("SELECT * FROM photos"))
    stats["total"] = len(rows)
    if not rows:
        conn.close()
        return stats

    cat_counter = Counter()
    fmt_counter = Counter()
    year_counter = Counter()
    location_counter = Counter()
    largest = []  # (size, filename, path)

    n_screenshot = n_noexif = n_gps = n_icloud_only = n_blur = n_favorite = 0

    for r in rows:
        d = dict(r)
        size = d.get("size_bytes") or 0
        stats["total_bytes"] += size

        media = d.get("media_type") or "image"
        if media == "video":
            stats["videos"] += 1
        else:
            stats["images"] += 1

        cat_counter[d.get("category") or "photo"] += 1
        fmt_counter[(d.get("format_family") or "other")] += 1

        dt = d.get("exif_datetime") or d.get("file_mtime") or ""
        if dt[:4].isdigit():
            year_counter[dt[:4]] += 1
            if not stats["date_min"] or dt < stats["date_min"]:
                stats["date_min"] = dt
            if not stats["date_max"] or dt > stats["date_max"]:
                stats["date_max"] = dt

        largest.append((size, d.get("filename") or "", d.get("file_path") or ""))

        # Health flags
        if (d.get("category") == "screenshot") or (cols & {"photos_screenshot"} and d.get("photos_screenshot")):
            n_screenshot += 1
        if "has_exif" in cols and not d.get("has_exif"):
            n_noexif += 1
        if d.get("gps_latitude") not in (None, "", 0):
            n_gps += 1
        if "photos_cloud_state" in cols and (d.get("photos_cloud_state") or 0) > 0:
            n_icloud_only += 1
        if "photos_favorite" in cols and d.get("photos_favorite"):
            n_favorite += 1
        # Possible blur via Apple sharp score
        qv = d.get("photos_quality_vector")
        if qv:
            try:
                vec = json.loads(qv) if isinstance(qv, str) else qv
                sharp = vec.get(SHARP_SCORE_KEY) if isinstance(vec, dict) else None
                if sharp is not None and float(sharp) < BLUR_THRESHOLD:
                    n_blur += 1
            except Exception:
                pass

        # Location (reverse-geocoded place names)
        city = d.get("place_city") or ""
        region = d.get("place_region") or ""
        country = d.get("place_country") or ""
        if city:
            location_counter[city] += 1
        elif country:
            location_counter[f"{country} (unknown city)"] += 1

    conn.close()

    largest.sort(reverse=True)
    stats["largest"] = [
        {"filename": fn, "size_bytes": sz, "size_human": format_size(sz), "path": p}
        for sz, fn, p in largest[:10]
    ]
    stats["by_category"] = dict(cat_counter.most_common())
    stats["by_format"] = dict(fmt_counter.most_common())
    stats["by_year"] = dict(sorted(year_counter.items()))
    stats["by_location"] = dict(location_counter.most_common(20))
    stats["total_size_human"] = format_size(stats["total_bytes"])
    stats["flags"] = {
        "screenshots": n_screenshot,
        "no_exif": n_noexif,
        "has_gps": n_gps,
        "icloud_only": n_icloud_only,
        "possible_blur": n_blur,
        "favorites": n_favorite,
    }
    return stats


def _bar(count: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return ""
    filled = int(round(width * count / total))
    return "█" * filled + "░" * (width - filled)


def print_terminal(stats: dict) -> None:
    """Print a human-readable health report to the terminal."""
    print("=" * 60)
    print("  SnapTidy — Library Health & Insights")
    print("=" * 60)
    if stats["total"] == 0:
        print("\n  ⚠️  No photos in this index.")
        return

    print(f"\n  📦 Total items : {stats['total']:,}  "
          f"({stats['images']:,} photos, {stats['videos']:,} videos)")
    print(f"  💾 Total size  : {stats['total_size_human']}")
    if stats["date_min"]:
        print(f"  📅 Date span   : {stats['date_min'][:10]} → {stats['date_max'][:10]}")

    print("\n  🏷️  By category")
    total = stats["total"]
    for cat, n in stats["by_category"].items():
        print(f"     {cat:12s} {_bar(n, total)} {n:>5} ({100*n/total:.0f}%)")

    print("\n  🖼️  By format")
    for fmt, n in stats["by_format"].items():
        print(f"     {fmt:12s} {_bar(n, total)} {n:>5} ({100*n/total:.0f}%)")

    if stats["by_year"]:
        print("\n  🗓️  By year")
        ymax = max(stats["by_year"].values())
        for year, n in stats["by_year"].items():
            print(f"     {year}  {_bar(n, ymax)} {n:>5}")

    if stats["by_location"]:
        print("\n  📍 By location (top 15)")
        loc_total = sum(stats["by_location"].values())
        for loc, n in list(stats["by_location"].items())[:15]:
            print(f"     {loc:25s} {_bar(n, loc_total)} {n:>5}")

    print("\n  🔍 Health flags")
    f = stats["flags"]
    print(f"     📱 Screenshots      : {f['screenshots']:>5}")
    print(f"     😶 No EXIF metadata : {f['no_exif']:>5}")
    print(f"     📍 With GPS (privacy): {f['has_gps']:>5}")
    print(f"     ☁️  iCloud-only      : {f['icloud_only']:>5}")
    print(f"     🌫️  Possibly blurry  : {f['possible_blur']:>5}")
    print(f"     ⭐ Favorites        : {f['favorites']:>5}")

    print("\n  📈 Top space consumers")
    for item in stats["largest"][:5]:
        print(f"     {item['size_human']:>9}  {item['filename']}")
    print()


def build_html(stats: dict) -> str:
    """Build a self-contained HTML health report."""
    import html as _html

    def esc(s):
        return _html.escape(str(s))

    total = stats["total"] or 1

    def bar_rows(mapping, color="#007AFF"):
        if not mapping:
            return "<p style='color:#86868b'>No data</p>"
        mx = max(mapping.values())
        out = []
        for k, v in mapping.items():
            pct = 100 * v / mx if mx else 0
            out.append(
                f"<div class='bar-row'><span class='bar-label'>{esc(k)}</span>"
                f"<div class='bar-track'><div class='bar-fill' style='width:{pct:.1f}%;background:{color}'></div></div>"
                f"<span class='bar-count'>{v}</span></div>"
            )
        return "\n".join(out)

    f = stats["flags"]
    flag_cards = [
        ("📱", "截图 Screenshots", f["screenshots"]),
        ("😶", "无 EXIF No EXIF", f["no_exif"]),
        ("📍", "含 GPS With GPS", f["has_gps"]),
        ("☁️", "仅 iCloud iCloud-only", f["icloud_only"]),
        ("🌫️", "可能模糊 Blurry", f["possible_blur"]),
        ("⭐", "收藏 Favorites", f["favorites"]),
    ]
    flag_html = "\n".join(
        f"<div class='flag-card'><div class='flag-ico'>{ico}</div>"
        f"<div class='flag-num'>{num}</div><div class='flag-lbl'>{esc(lbl)}</div></div>"
        for ico, lbl, num in flag_cards
    )

    largest_html = "\n".join(
        f"<tr><td>{esc(it['filename'])}</td><td style='text-align:right'>{esc(it['size_human'])}</td></tr>"
        for it in stats["largest"]
    )

    date_span = ""
    if stats["date_min"]:
        date_span = f"{esc(stats['date_min'][:10])} ~ {esc(stats['date_max'][:10])}"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SnapTidy — 照片库健康报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f5f7;color:#1d1d1f;padding:24px;line-height:1.5}}
.container{{max-width:960px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1d1d1f 0%,#3a3a3c 100%);color:#fff;border-radius:16px;padding:32px;margin-bottom:24px}}
.header h1{{font-size:26px;font-weight:700;margin-bottom:4px}}
.header .sub{{color:#aeaeb2;font-size:14px}}
.header .meta{{margin-top:16px;display:flex;gap:32px;flex-wrap:wrap}}
.header .mv{{font-size:22px;font-weight:600}}
.header .ml{{font-size:11px;color:#aeaeb2;text-transform:uppercase;letter-spacing:.5px}}
.card{{background:#fff;border-radius:14px;padding:24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.card h2{{font-size:17px;margin-bottom:16px}}
.bar-row{{display:flex;align-items:center;gap:12px;margin-bottom:8px}}
.bar-label{{width:120px;font-size:13px;color:#1d1d1f}}
.bar-track{{flex:1;height:18px;background:#f0f0f2;border-radius:9px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:9px}}
.bar-count{{width:50px;text-align:right;font-size:13px;color:#86868b}}
.flags{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:14px}}
.flag-card{{background:#f5f5f7;border-radius:12px;padding:18px;text-align:center}}
.flag-ico{{font-size:26px}}
.flag-num{{font-size:24px;font-weight:700;margin:4px 0}}
.flag-lbl{{font-size:11px;color:#86868b}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td{{padding:8px 4px;border-bottom:1px solid #f0f0f2}}
</style></head>
<body><div class="container">
<div class="header">
  <h1>📊 照片库健康报告</h1>
  <div class="sub">Library Health &amp; Insights · {esc(os.path.basename(stats['index_path']))}</div>
  <div class="meta">
    <div><div class="mv">{stats['total']:,}</div><div class="ml">Total items</div></div>
    <div><div class="mv">{esc(stats.get('total_size_human',''))}</div><div class="ml">Total size</div></div>
    <div><div class="mv">{stats['images']:,}</div><div class="ml">Photos</div></div>
    <div><div class="mv">{stats['videos']:,}</div><div class="ml">Videos</div></div>
    <div><div class="mv" style="font-size:15px">{date_span}</div><div class="ml">Date span</div></div>
  </div>
</div>
<div class="card"><h2>🏷️ 类别分布 By category</h2>{bar_rows(stats['by_category'], '#007AFF')}</div>
<div class="card"><h2>🖼️ 格式分布 By format</h2>{bar_rows(stats['by_format'], '#FF9500')}</div>
<div class="card"><h2>🗓️ 年度分布 By year</h2>{bar_rows(stats['by_year'], '#34C759')}</div>
<div class="card"><h2>📍 地点分布 By location</h2>{bar_rows(stats['by_location'], '#AF52DE')}</div>
<div class="card"><h2>🔍 健康指标 Health flags</h2><div class="flags">{flag_html}</div></div>
<div class="card"><h2>📈 占用空间最大的文件 Top space consumers</h2><table>{largest_html}</table></div>
</div></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Library health & insights (read-only) over a scanned index")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index (from scan_photos.py)")
    parser.add_argument("--report", "--output", "-o", dest="report", default="",
                        help="Optional HTML report output path")
    parser.add_argument("--format", choices=["terminal", "json"], default="terminal",
                        help="Console output format (default: terminal)")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"❌ Index not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    stats = collect_stats(args.index)

    if args.format == "json":
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print_terminal(stats)

    if args.report:
        report_path = os.path.abspath(args.report)
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(build_html(stats))
        print(f"  📄 HTML report: {report_path}")


if __name__ == "__main__":
    main()
