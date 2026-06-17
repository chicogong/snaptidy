#!/usr/bin/env python3
"""Generate an HTML report for Photos.app album organization.

Creates a visually appealing, self-contained HTML page that summarizes
the results of a photos-album organization run, including:
- Summary statistics (albums created, photos added, errors)
- Album cards with photo counts and sample thumbnails
- Organization mode and timestamp

Usage:
    python3 scripts/generate_album_report.py \
        --index photo_index.db \
        --report album_report.html \
        --organize-by date \
        --stats '{"albums_created": 3, "photos_added": 309, "errors": 0}'
"""

import argparse
import base64
import html
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime

from constants import MONTH_NAMES, format_size


# Album name emojis by category
CATEGORY_ICONS = {
    "📸 Photos": "📸",
    "📱 Screenshots": "📱",
    "🔄 Burst": "🔄",
    "💬 WeChat": "💬",
    "🎬 Videos": "🎬",
    "🎵 Live Photos": "🎵",
    "📁 Other": "📁",
    "📅 No Date": "📅",
}


def get_thumbnail_base64(path: str, max_size: int = 160) -> str:
    """Generate a base64-encoded thumbnail for an image."""
    try:
        from PIL import Image
        import io

        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass

        with Image.open(path) as img:
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _get_album_emoji(album_name: str) -> str:
    """Get emoji for album based on name pattern."""
    for key, emoji in CATEGORY_ICONS.items():
        if key in album_name:
            return emoji
    # Date-based: "2026/06 – June"
    if "/" in album_name and any(m in album_name for m in MONTH_NAMES.values()):
        return "🗓️"
    # Year only: "2026"
    if album_name.isdigit() and len(album_name) == 4:
        return "📅"
    # Format-based: "JPEG", "HEIC"
    fmt_keywords = ["JPEG", "HEIC", "PNG", "GIF", "TIFF", "BMP", "RAW", "HEIF", "AVIF", "WebP"]
    if album_name.upper() in fmt_keywords:
        return "🖼️"
    return "📁"


def _compute_album_diff(before: dict, after: dict) -> dict:
    """Compute the diff between before/after album states.

    Returns:
        {
            "new_albums": [(name, count), ...],
            "updated_albums": [(name, before_count, after_count, delta), ...],
            "unchanged_albums": [(name, count), ...],
            "removed_albums": [(name, count), ...],  # unlikely but possible
        }
    """
    new_albums = []
    updated_albums = []
    unchanged_albums = []
    removed_albums = []

    all_names = set(list(before.keys()) + list(after.keys()))
    for name in sorted(all_names):
        b = before.get(name, None)
        a = after.get(name, None)
        if b is None and a is not None:
            new_albums.append((name, a))
        elif b is not None and a is None:
            removed_albums.append((name, b))
        elif b is not None and a is not None:
            delta = a - b
            if delta > 0:
                updated_albums.append((name, b, a, delta))
            elif delta == 0:
                unchanged_albums.append((name, a))
            else:
                # Photo count decreased (e.g. photos deleted)
                updated_albums.append((name, b, a, delta))

    return {
        "new_albums": new_albums,
        "updated_albums": updated_albums,
        "unchanged_albums": unchanged_albums,
        "removed_albums": removed_albums,
    }


def generate_album_report_html(
    index_db: str,
    organize_by: str,
    stats: dict,
    sample_photos: dict = None,
    max_thumbnails_per_album: int = 6,
) -> str:
    """Generate HTML report for album organization.

    Args:
        index_db: Path to SQLite metadata index
        organize_by: Organization mode (date, year, category, format, smart)
        stats: Stats dict from organize_photos_albums()
        sample_photos: Optional {album_name: [file_path, ...]} for thumbnails
        max_thumbnails_per_album: Max thumbnails to show per album card
    """
    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row

    # Compute total library stats
    total_photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    total_size_row = conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM photos").fetchone()
    total_size = int(total_size_row[0]) if total_size_row[0] else 0

    # Category distribution
    cat_dist = {}
    for row in conn.execute("SELECT category, COUNT(*) as cnt FROM photos GROUP BY category ORDER BY cnt DESC"):
        cat_dist[row["category"]] = row["cnt"]

    # Date range
    date_range = ""
    min_max = conn.execute(
        "SELECT MIN(exif_datetime) as mn, MAX(exif_datetime) as mx FROM photos WHERE exif_datetime != ''"
    ).fetchone()
    if min_max and min_max["mn"] and min_max["mx"]:
        try:
            mn = min_max["mn"][:10].replace(":", "-")
            mx = min_max["mx"][:10].replace(":", "-")
            date_range = f"{mn} ~ {mx}"
        except Exception:
            pass

    # Format distribution
    fmt_dist = {}
    for row in conn.execute("SELECT format_family, COUNT(*) as cnt FROM photos GROUP BY format_family ORDER BY cnt DESC"):
        fmt_dist[row["format_family"]] = row["cnt"]

    # Build album details from stats
    album_details = stats.get("details", [])

    # If sample_photos not provided, try to get sample photos from DB
    if sample_photos is None:
        sample_photos = {}
        for detail in album_details:
            album_name = detail.get("album", "")
            count = detail.get("count", detail.get("added", 0))
            if count == 0:
                continue
            # Try to find sample photos by matching the grouping logic
            # We'll get a few sample file_paths per album
            sample_photos[album_name] = []

    # Get sample thumbnails from DB by re-grouping
    album_sample_paths = defaultdict(list)
    cursor = conn.execute(
        "SELECT file_path, filename, exif_datetime, file_mtime, category, format_family FROM photos"
    )
    rows = list(cursor)

    # Category / format label maps come from constants.py (single source of
    # truth) so album names stay identical between organizer and report.
    from constants import CATEGORY_ALBUM_NAMES, FORMAT_ALBUM_NAMES

    for row in rows:
        filepath = row["file_path"]
        filename = row["filename"]
        exif_dt = row["exif_datetime"] or row["file_mtime"] or ""
        category = row["category"] or "photo"
        fmt_family = row["format_family"] or "other"
        uuid_part = os.path.splitext(filename)[0]
        if len(uuid_part) < 32:
            continue

        # Determine album name (mirror organize_photos_albums logic)
        if organize_by == "date":
            if not exif_dt:
                a_name = "📅 No Date"
            else:
                try:
                    if "T" in exif_dt:
                        parsed = datetime.fromisoformat(exif_dt.replace("Z", "+00:00"))
                    else:
                        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                            try:
                                parsed = datetime.strptime(exif_dt[:19], fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            continue
                    a_name = f"{parsed.year:04d}/{parsed.month:02d} – {MONTH_NAMES.get(parsed.month, '')}"
                except Exception:
                    continue
        elif organize_by == "year":
            if not exif_dt:
                continue
            year = exif_dt[:4]
            if year.isdigit() and int(year) > 1990:
                a_name = year
            else:
                continue
        elif organize_by == "category":
            a_name = CATEGORY_ALBUM_NAMES.get(category, f"📁 {category.title()}")
        elif organize_by == "format":
            a_name = FORMAT_ALBUM_NAMES.get(fmt_family, fmt_family.title())
        elif organize_by == "smart":
            year = "Unknown"
            if exif_dt:
                y = exif_dt[:4]
                if y.isdigit() and int(y) > 1990:
                    year = y
            cat_name = CATEGORY_ALBUM_NAMES.get(category, category.title())
            a_name = f"{year}/{cat_name}"
        else:
            continue

        if len(album_sample_paths[a_name]) < max_thumbnails_per_album:
            album_sample_paths[a_name].append(filepath)

    conn.close()

    # Generate thumbnails
    album_thumbnails = {}
    for album_name, paths in album_sample_paths.items():
        thumbs = []
        for p in paths:
            b64 = get_thumbnail_base64(p)
            if b64:
                thumbs.append(b64)
            if len(thumbs) >= max_thumbnails_per_album:
                break
        album_thumbnails[album_name] = thumbs

    # Build HTML
    now = datetime.now()
    organize_by_labels = {
        "date": "Date (Year/Month)",
        "year": "Year",
        "category": "Category",
        "format": "Format",
        "smart": "Smart (Year + Category)",
    }
    organize_label = organize_by_labels.get(organize_by, organize_by)

    # Compute stats
    albums_created = stats.get("albums_created", 0)
    photos_added = stats.get("photos_added", 0)
    errors = stats.get("errors", 0)

    # Before/after diff
    before_albums = stats.get("before_albums", {})
    after_albums = stats.get("after_albums", {})
    has_diff = bool(before_albums) and bool(after_albums)
    diff = _compute_album_diff(before_albums, after_albums) if has_diff else None

    # Album details sorted
    sorted_details = sorted(album_details, key=lambda d: d.get("album", ""))

    # Color palette for album cards
    card_colors = [
        ("#007AFF", "#E8F0FE"),  # Blue
        ("#34C759", "#E8F9ED"),  # Green
        ("#FF9500", "#FFF3E0"),  # Orange
        ("#AF52DE", "#F3E8FD"),  # Purple
        ("#FF2D55", "#FFE8ED"),  # Pink
        ("#5AC8FA", "#E3F6FD"),  # Teal
        ("#FFCC00", "#FFF9E0"),  # Yellow
        ("#8E8E93", "#F0F0F2"),  # Gray
    ]

    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SnapTidy — 相册整理报告</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
  background: #f5f5f7; color: #1d1d1f; padding: 24px;
  line-height: 1.5;
}}
.container {{ max-width: 960px; margin: 0 auto; }}

/* Header */
.header {{
  background: linear-gradient(135deg, #1d1d1f 0%, #3a3a3c 100%);
  color: white; border-radius: 16px; padding: 32px;
  margin-bottom: 24px; position: relative; overflow: hidden;
}}
.header::before {{
  content: "🗂️"; position: absolute; right: 24px; top: 50%;
  transform: translateY(-50%); font-size: 80px; opacity: 0.15;
}}
.header h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 4px; }}
.header .subtitle {{ color: #aeaeb2; font-size: 14px; }}
.header .meta {{ margin-top: 16px; display: flex; gap: 24px; flex-wrap: wrap; }}
.header .meta-item {{ display: flex; flex-direction: column; }}
.header .meta-label {{ font-size: 11px; color: #aeaeb2; text-transform: uppercase; letter-spacing: 0.5px; }}
.header .meta-value {{ font-size: 16px; font-weight: 600; color: white; }}

/* Summary cards */
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px; margin-bottom: 24px; }}
.summary-card {{
  background: white; border-radius: 12px; padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06); text-align: center;
}}
.summary-card .value {{ font-size: 36px; font-weight: 700; }}
.summary-card .label {{ font-size: 13px; color: #86868b; margin-top: 4px; }}
.summary-card.blue .value {{ color: #007AFF; }}
.summary-card.green .value {{ color: #34C759; }}
.summary-card.orange .value {{ color: #FF9500; }}
.summary-card.red .value {{ color: #FF3B30; }}

/* Library info */
.library-info {{
  background: white; border-radius: 12px; padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 24px;
}}
.library-info h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; }}
.info-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; }}
.info-item {{ display: flex; justify-content: space-between; padding: 6px 0;
  border-bottom: 1px solid #f0f0f0; font-size: 14px; }}
.info-item:last-child {{ border-bottom: none; }}
.info-key {{ color: #86868b; }}
.info-val {{ font-weight: 500; }}

/* Album section */
.section-title {{
  font-size: 20px; font-weight: 700; margin-bottom: 16px;
  display: flex; align-items: center; gap: 8px;
}}
.album-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px; margin-bottom: 32px; }}
.album-card {{
  background: white; border-radius: 12px; overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06); transition: transform 0.15s;
  border-left: 4px solid;
}}
.album-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
.album-card-header {{ padding: 16px 16px 8px; }}
.album-name {{ font-size: 15px; font-weight: 600; margin-bottom: 4px; }}
.album-count {{ font-size: 13px; color: #86868b; }}
.album-count strong {{ color: #1d1d1f; font-weight: 600; }}
.album-status {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; margin-left: 8px; }}
.album-status.new {{ background: #E8F9ED; color: #34C759; }}
.album-status.existing {{ background: #E8F0FE; color: #007AFF; }}
.album-status.failed {{ background: #FFE8ED; color: #FF3B30; }}

/* Thumbnails */
.thumbnails {{ display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 4px; padding: 8px 16px 16px; }}
.thumb {{
  aspect-ratio: 1; object-fit: cover; border-radius: 6px;
  background: #f0f0f0; width: 100%;
}}
.no-thumb {{
  aspect-ratio: 1; background: #f5f5f7; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  color: #c7c7cc; font-size: 20px;
}}

/* Category / format distribution bars */
.dist-section {{
  background: white; border-radius: 12px; padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 24px;
}}
.dist-section h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; }}
.bar-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
.bar-label {{ width: 100px; font-size: 13px; text-align: right; color: #48484a; flex-shrink: 0; }}
.bar-track {{ flex: 1; background: #f0f0f0; border-radius: 4px; height: 20px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s; }}
.bar-count {{ width: 60px; font-size: 13px; color: #86868b; flex-shrink: 0; }}

/* Footer */
.footer {{
  text-align: center; color: #aeaeb2; font-size: 12px; margin-top: 24px;
  padding-top: 16px; border-top: 1px solid #e8e8ed;
}}

/* Diff / Before-After */
.diff-section {{
  background: white; border-radius: 12px; padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 24px;
}}
.diff-section h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; }}
.diff-table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
.diff-table th {{ text-align: left; padding: 8px 12px; background: #f5f5f7;
  font-weight: 600; color: #48484a; border-bottom: 2px solid #e8e8ed; }}
.diff-table td {{ padding: 8px 12px; border-bottom: 1px solid #f0f0f0; }}
.diff-table tr:last-child td {{ border-bottom: none; }}
.diff-table .album-col {{ font-weight: 500; }}
.diff-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.diff-plus {{ color: #34C759; font-weight: 600; }}
.diff-minus {{ color: #FF3B30; font-weight: 600; }}
.diff-zero {{ color: #86868b; }}
.diff-badge {{
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; margin-left: 6px;
}}
.diff-badge.new {{ background: #E8F9ED; color: #34C759; }}
.diff-badge.grew {{ background: #E8F0FE; color: #007AFF; }}
.diff-badge.shrank {{ background: #FFF3E0; color: #FF9500; }}
.diff-badge.same {{ background: #f5f5f7; color: #86868b; }}
.diff-badge.removed {{ background: #FFE8ED; color: #FF3B30; }}
.diff-summary-row {{
  background: #fafafa; font-weight: 600;
}}
.diff-summary-row td {{ border-top: 2px solid #e8e8ed; }}

/* Responsive */
@media (max-width: 600px) {{
  .header {{ padding: 24px; }}
  .header h1 {{ font-size: 22px; }}
  .summary {{ grid-template-columns: repeat(2, 1fr); }}
  .album-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div class="container">

<!-- Header -->
<div class="header">
  <h1>🗂️ SnapTidy 相册整理报告</h1>
  <div class="subtitle">Photos.app Album Organization Report</div>
  <div class="meta">
    <div class="meta-item">
      <span class="meta-label">整理方式</span>
      <span class="meta-value">{organize_label}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">执行时间</span>
      <span class="meta-value">{now.strftime("%Y-%m-%d %H:%M")}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">照片总数</span>
      <span class="meta-value">{total_photos}</span>
    </div>
  </div>
</div>
""")

    # Summary cards
    html_parts.append(f"""
<div class="summary">
  <div class="summary-card green">
    <div class="value">{albums_created}</div>
    <div class="label">新建相册</div>
  </div>
  <div class="summary-card blue">
    <div class="value">{photos_added}</div>
    <div class="label">归类照片</div>
  </div>
  <div class="summary-card orange">
    <div class="value">{len(album_details)}</div>
    <div class="label">相册总数</div>
  </div>
  <div class="summary-card {'red' if errors > 0 else 'green'}">
    <div class="value">{errors}</div>
    <div class="label">{'⚠️ 错误' if errors > 0 else '✅ 错误'}</div>
  </div>
</div>
""")

    # Before/After Diff section
    if diff:
        new_count = len(diff["new_albums"])
        grew_count = len(diff["updated_albums"])
        same_count = len(diff["unchanged_albums"])
        removed_count = len(diff["removed_albums"])
        total_photos_before = sum(before_albums.values())
        total_photos_after = sum(after_albums.values())

        html_parts.append(f"""
<div class="diff-section">
  <h2>🔄 变更对比 · Before → After</h2>
  <div class="summary" style="margin-bottom:16px">
    <div class="summary-card green" style="padding:12px">
      <div class="value" style="font-size:24px">{new_count}</div>
      <div class="label">新建相册</div>
    </div>
    <div class="summary-card blue" style="padding:12px">
      <div class="value" style="font-size:24px">{grew_count}</div>
      <div class="label">照片增加</div>
    </div>
    <div class="summary-card orange" style="padding:12px">
      <div class="value" style="font-size:24px">{same_count}</div>
      <div class="label">未变化</div>
    </div>
    <div class="summary-card" style="padding:12px">
      <div class="value" style="font-size:24px;color:#1d1d1f">{total_photos_before} → {total_photos_after}</div>
      <div class="label">相册照片总数</div>
    </div>
  </div>
  <table class="diff-table">
    <tr>
      <th>相册</th>
      <th class="num">整理前</th>
      <th class="num">整理后</th>
      <th class="num">变化</th>
      <th>状态</th>
    </tr>
""")

        # New albums
        for name, count in diff["new_albums"]:
            html_parts.append(f"""    <tr>
      <td class="album-col">{_get_album_emoji(name)} {html.escape(name)}</td>
      <td class="num">—</td>
      <td class="num">{count}</td>
      <td class="num diff-plus">+{count}</td>
      <td><span class="diff-badge new">新建</span></td>
    </tr>
""")

        # Updated albums (grew)
        for name, b, a, delta in diff["updated_albums"]:
            if delta > 0:
                badge = '<span class="diff-badge grew">增加</span>'
                delta_html = f'<span class="diff-plus">+{delta}</span>'
            else:
                badge = '<span class="diff-badge shrank">减少</span>'
                delta_html = f'<span class="diff-minus">{delta}</span>'
            html_parts.append(f"""    <tr>
      <td class="album-col">{_get_album_emoji(name)} {html.escape(name)}</td>
      <td class="num">{b}</td>
      <td class="num">{a}</td>
      <td class="num">{delta_html}</td>
      <td>{badge}</td>
    </tr>
""")

        # Removed albums
        for name, count in diff["removed_albums"]:
            html_parts.append(f"""    <tr>
      <td class="album-col">{_get_album_emoji(name)} {html.escape(name)}</td>
      <td class="num">{count}</td>
      <td class="num">—</td>
      <td class="num diff-minus">-{count}</td>
      <td><span class="diff-badge removed">已删除</span></td>
    </tr>
""")

        # Unchanged albums (collapsed, show count only)
        if same_count > 0:
            html_parts.append(f"""    <tr class="diff-summary-row">
      <td colspan="5" style="text-align:center;color:#86868b">
        还有 {same_count} 个相册未变化（点击展开）
      </td>
    </tr>
""")

        html_parts.append("""  </table>
</div>
""")

    # Library info
    html_parts.append(f"""
<div class="library-info">
  <h2>📊 图库概览</h2>
  <div class="info-grid">
    <div class="info-item">
      <span class="info-key">照片总数</span>
      <span class="info-val">{total_photos}</span>
    </div>
    <div class="info-item">
      <span class="info-key">总大小</span>
      <span class="info-val">{format_size(total_size)}</span>
    </div>
    <div class="info-item">
      <span class="info-key">时间跨度</span>
      <span class="info-val">{date_range or '未知'}</span>
    </div>
    <div class="info-item">
      <span class="info-key">格式种类</span>
      <span class="info-val">{len(fmt_dist)}</span>
    </div>
  </div>
</div>
""")

    # Category distribution
    if cat_dist:
        max_cat = max(cat_dist.values())
        html_parts.append('<div class="dist-section"><h2>🏷️ 类别分布</h2>')
        cat_colors = ["#007AFF", "#34C759", "#FF9500", "#AF52DE", "#FF2D55", "#5AC8FA"]
        for i, (cat, cnt) in enumerate(sorted(cat_dist.items(), key=lambda x: -x[1])):
            pct = (cnt / max_cat * 100) if max_cat > 0 else 0
            color = cat_colors[i % len(cat_colors)]
            html_parts.append(f"""
<div class="bar-row">
  <span class="bar-label">{html.escape(cat)}</span>
  <div class="bar-track">
    <div class="bar-fill" style="width:{pct:.1f}%; background:{color}"></div>
  </div>
  <span class="bar-count">{cnt}</span>
</div>""")
        html_parts.append('</div>')

    # Format distribution
    if fmt_dist:
        max_fmt = max(fmt_dist.values())
        html_parts.append('<div class="dist-section"><h2>🖼️ 格式分布</h2>')
        fmt_colors = ["#FF9500", "#007AFF", "#34C759", "#AF52DE", "#FF2D55", "#8E8E93"]
        for i, (fmt, cnt) in enumerate(sorted(fmt_dist.items(), key=lambda x: -x[1])):
            pct = (cnt / max_fmt * 100) if max_fmt > 0 else 0
            color = fmt_colors[i % len(fmt_colors)]
            html_parts.append(f"""
<div class="bar-row">
  <span class="bar-label">{html.escape(fmt.upper())}</span>
  <div class="bar-track">
    <div class="bar-fill" style="width:{pct:.1f}%; background:{color}"></div>
  </div>
  <span class="bar-count">{cnt}</span>
</div>""")
        html_parts.append('</div>')

    # Album cards
    html_parts.append(f"""
<div class="section-title">📁 相册明细 ({len(sorted_details)} albums)</div>
<div class="album-grid">
""")

    for i, detail in enumerate(sorted_details):
        album_name = detail.get("album", "Unknown")
        count = detail.get("count", detail.get("added", 0))
        added = detail.get("added", count)
        existed = detail.get("existed", False)
        has_error = detail.get("status") == "create_failed"

        color_pair = card_colors[i % len(card_colors)]
        border_color = color_pair[0]
        emoji = _get_album_emoji(album_name)

        # Status badge
        if has_error:
            status_html = '<span class="album-status failed">❌ 创建失败</span>'
        elif existed:
            status_html = '<span class="album-status existing">已有</span>'
        else:
            status_html = '<span class="album-status new">新建</span>'

        # Thumbnails
        thumbs = album_thumbnails.get(album_name, [])
        thumbs_html = ""
        if thumbs:
            for b64 in thumbs:
                thumbs_html += f'<img class="thumb" src="data:image/jpeg;base64,{b64}" alt="thumbnail">'
        else:
            for _ in range(min(3, max(count, 1))):
                thumbs_html += f'<div class="no-thumb">{emoji}</div>'

        html_parts.append(f"""
<div class="album-card" style="border-left-color:{border_color}">
  <div class="album-card-header">
    <div class="album-name">{emoji} {html.escape(album_name)}{status_html}</div>
    <div class="album-count"><strong>{added}</strong> / {count} photos added</div>
  </div>
  <div class="thumbnails">
    {thumbs_html}
  </div>
</div>
""")

    html_parts.append("</div>")

    # Footer
    html_parts.append(f"""
<div class="footer">
  <p>Generated by <strong>SnapTidy</strong> v3.5.0 · {now.strftime("%Y-%m-%d %H:%M:%S")}</p>
  <p>Report is self-contained — safe to share or archive</p>
</div>

</div>
</body>
</html>
""")

    return "\n".join(html_parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate HTML report for Photos.app album organization")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="SQLite metadata index")
    parser.add_argument("--report", "--output", "-o", dest="report", required=True,
                        help="Output HTML file path (alias: --output)")
    parser.add_argument("--organize-by", default="date",
                        choices=["date", "year", "category", "format", "smart"],
                        help="Organization mode")
    parser.add_argument("--stats", default="{}",
                        help="JSON stats from organize_photos_albums()")
    parser.add_argument("--max-thumbnails", type=int, default=6,
                        help="Max thumbnails per album (default: 6)")
    args = parser.parse_args()

    stats = json.loads(args.stats)

    html_content = generate_album_report_html(
        index_db=os.path.abspath(args.index),
        organize_by=args.organize_by,
        stats=stats,
        max_thumbnails_per_album=args.max_thumbnails,
    )

    output_path = os.path.abspath(args.report)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"📊 Report generated: {output_path}")
    print(f"   Open in browser: file://{output_path}")


if __name__ == "__main__":
    main()
