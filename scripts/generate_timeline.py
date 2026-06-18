#!/usr/bin/env python3
"""Generate an interactive timeline view of your photo library.

Creates a self-contained HTML page with a zoomable timeline organized by
year → month → day. Supports thumbnail previews, category filtering,
and click-to-browse navigation.

Features:
  - Zoom levels: year / month / day
  - Category filters: all, photo, screenshot, wechat, burst, video
  - Quality overlay: shows quality_score badge if available
  - Album display for Photos.app library scans
  - Responsive layout, standalone HTML (no server needed)

Usage:
    python3 scripts/generate_timeline.py --index photo_index.db --output timeline.html

    # Limit number of photos per day (faster rendering for large libraries)
    python3 scripts/generate_timeline.py --index photo_index.db --output timeline.html --max-per-day 20

    # Filter by year range
    python3 scripts/generate_timeline.py --index photo_index.db --output timeline.html --from-year 2023 --to-year 2026
"""

import argparse
import base64
import json
import os
import sqlite3
import sys
from collections import defaultdict

from constants import format_size


def get_thumbnail_base64(path: str, max_size: int = 150) -> str:
    """Create a base64 JPEG thumbnail for embedding in HTML."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.Resampling.BILINEAR)
            import io
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def build_timeline_data(index_path: str, max_per_day: int = 0,
                        from_year: int = 0, to_year: int = 0) -> dict:
    """Build timeline data structure from index DB.

    Returns: {years: [{year, months: [{month, days: [{day, photos: [...]}]}]}],
              events: {event_id: {name, start_date, end_date, city, photo_count}},
              no_date_count: int}
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}

    select_fields = ["file_path", "filename", "extension", "size_bytes",
                     "width", "height", "category", "media_type",
                     "exif_datetime", "file_mtime"]
    for col in ("camera_make", "camera_model", "place_city", "place_country",
                "quality_score", "photos_albums", "photos_favorite",
                "event_id", "live_photo_group"):
        if col in available_cols:
            select_fields.append(col)

    query = f"SELECT {', '.join(select_fields)} FROM photos"
    conditions = []
    if from_year:
        conditions.append(f"(substr(exif_datetime,1,4) >= '{from_year}' OR substr(file_mtime,1,4) >= '{from_year}')")
    if to_year:
        conditions.append(f"(substr(exif_datetime,1,4) <= '{to_year}' OR substr(file_mtime,1,4) <= '{to_year}')")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor = conn.execute(query)
    rows = cursor.fetchall()
    conn.close()

    # Group by year → month → day
    year_map = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    no_date = []

    # Also build events index: event_id -> {name, start, end, city, photos}
    events_index = {}

    for row in rows:
        d = dict(row)
        # Determine date
        dt_str = d.get("exif_datetime") or d.get("file_mtime") or ""
        if dt_str and len(dt_str) >= 10:
            year = dt_str[:4]
            month = dt_str[5:7]
            day = dt_str[8:10]
            year_map[year][month][day].append(d)
        else:
            no_date.append(d)

        # Collect event info
        eid = d.get("event_id") or ""
        if eid:
            if eid not in events_index:
                events_index[eid] = {
                    "id": eid,
                    "city": d.get("place_city") or "",
                    "country": d.get("place_country") or "",
                    "start_date": dt_str[:10] if dt_str else "",
                    "end_date": dt_str[:10] if dt_str else "",
                    "photo_count": 0,
                }
            events_index[eid]["photo_count"] += 1
            # Update date range
            if dt_str and dt_str[:10]:
                if not events_index[eid]["start_date"] or dt_str[:10] < events_index[eid]["start_date"]:
                    events_index[eid]["start_date"] = dt_str[:10]
                if not events_index[eid]["end_date"] or dt_str[:10] > events_index[eid]["end_date"]:
                    events_index[eid]["end_date"] = dt_str[:10]
            # Build event name
            city = events_index[eid]["city"]
            start = events_index[eid]["start_date"]
            if city:
                events_index[eid]["name"] = f"{city} ({start})"
            else:
                events_index[eid]["name"] = f"Event {eid} ({start})"

    # Build nested structure
    years = []
    for year in sorted(year_map.keys(), reverse=True):
        months = []
        for month in sorted(year_map[year].keys()):
            days = []
            for day in sorted(year_map[year][month].keys()):
                photos = year_map[year][month][day]
                if max_per_day and len(photos) > max_per_day:
                    photos = photos[:max_per_day]
                days.append({"day": day, "count": len(year_map[year][month][day]),
                             "photos": photos})
            month_count = sum(d["count"] for d in days)
            months.append({"month": month, "count": month_count, "days": days})
        year_count = sum(m["count"] for m in months)
        years.append({"year": year, "count": year_count, "months": months})

    return {"years": years, "no_date_count": len(no_date), "events": events_index}


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SnapTidy Timeline</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f7; color: #1d1d1f; }

.header { background: #fff; border-bottom: 1px solid #d1d1d6; padding: 16px 24px; position: sticky; top: 0; z-index: 100; }
.header h1 { font-size: 20px; font-weight: 600; }
.controls { display: flex; gap: 12px; margin-top: 10px; align-items: center; flex-wrap: wrap; }
.controls select, .controls button { padding: 6px 12px; border-radius: 8px; border: 1px solid #d1d1d6; font-size: 13px; }
.controls button { background: #007aff; color: white; border: none; cursor: pointer; }
.controls button:hover { background: #0056cc; }
.controls .stat { font-size: 12px; color: #86868b; }

.content { max-width: 1400px; margin: 0 auto; padding: 20px; }

.year-block { margin-bottom: 32px; }
.year-header { display: flex; align-items: center; gap: 12px; cursor: pointer; padding: 12px 16px; background: #fff; border-radius: 12px; margin-bottom: 12px; }
.year-header:hover { background: #e8e8ed; }
.year-header h2 { font-size: 28px; font-weight: 700; }
.year-header .count { font-size: 14px; color: #86868b; }
.year-header .toggle { font-size: 18px; color: #86868b; }

.month-section { margin-left: 16px; margin-bottom: 16px; }
.month-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #fff; border-radius: 8px; margin-bottom: 8px; cursor: pointer; }
.month-header:hover { background: #e8e8ed; }
.month-name { font-size: 16px; font-weight: 600; }
.month-count { font-size: 12px; color: #86868b; }

.day-section { margin-left: 16px; margin-bottom: 12px; }
.day-header { font-size: 13px; color: #86868b; padding: 4px 8px; margin-bottom: 6px; }
.photo-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.photo-thumb { position: relative; width: 100px; height: 100px; border-radius: 8px; overflow: hidden; background: #e8e8ed; cursor: pointer; }
.photo-thumb img { width: 100%; height: 100%; object-fit: cover; }
.photo-thumb .badge { position: absolute; top: 4px; right: 4px; font-size: 9px; padding: 2px 5px; border-radius: 4px; color: white; font-weight: 600; }
.badge-photo { background: #34c759; }
.badge-screenshot { background: #ff9500; }
.badge-wechat { background: #07c160; }
.badge-burst { background: #5856d6; }
.badge-video { background: #ff2d55; }
.quality-badge { position: absolute; bottom: 4px; left: 4px; font-size: 9px; padding: 2px 5px; border-radius: 4px; color: white; font-weight: 600; }
.event-tag { position: absolute; bottom: 4px; right: 4px; font-size: 8px; padding: 1px 4px; border-radius: 3px; color: white; font-weight: 500; max-width: 60px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.q-high { background: #34c759; }
.q-mid { background: #ff9500; }
.q-low { background: #ff3b30; }

.event-banner { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 8px 16px; border-radius: 8px; margin: 8px 0 4px 16px; font-size: 13px; display: flex; justify-content: space-between; align-items: center; }
.event-banner .event-name { font-weight: 600; }
.event-banner .event-dates { font-size: 11px; opacity: 0.85; }

.empty { text-align: center; padding: 60px 20px; color: #86868b; }
.empty h3 { font-size: 18px; margin-bottom: 8px; }

@media (max-width: 768px) {
  .photo-thumb { width: 80px; height: 80px; }
  .year-header h2 { font-size: 22px; }
}

/* Dark mode */
@media (prefers-color-scheme: dark) {
  body { background: #1c1c1e; color: #e5e5e7; }
  .header { background: #2c2c2e; border-bottom-color: #38383a; }
  .header h1 { color: #e5e5e7; }
  .controls select { background: #2c2c2e; border-color: #48484a; color: #e5e5e7; }
  .controls .stat { color: #98989d; }
  .year-header { background: #2c2c2e; }
  .year-header:hover { background: #3a3a3c; }
  .year-header .count { color: #98989d; }
  .year-header .toggle { color: #98989d; }
  .month-header { background: #2c2c2e; }
  .month-header:hover { background: #3a3a3c; }
  .month-count { color: #98989d; }
  .day-header { color: #98989d; }
  .photo-thumb { background: #3a3a3c; }
  .empty { color: #636366; }
  .empty h3 { color: #98989d; }
}
</style>
</head>
<body>
<div class="header">
  <h1>📸 SnapTidy Timeline</h1>
  <div class="controls">
    <label>缩放:</label>
    <select id="zoom" onchange="applyZoom()">
      <option value="day">日</option>
      <option value="month">月</option>
      <option value="year">年</option>
    </select>
    <label>类别:</label>
    <select id="category" onchange="applyFilter()">
      <option value="all">全部</option>
      <option value="photo">照片</option>
      <option value="screenshot">截图</option>
      <option value="wechat">微信</option>
      <option value="burst">连拍</option>
      <option value="video">视频</option>
    </select>
    <button onclick="collapseAll()">全部折叠</button>
    <button onclick="expandAll()">全部展开</button>
    <label>事件:</label>
    <select id="eventFilter" onchange="applyFilter()">
      <option value="all">全部事件</option>
    </select>
    <span class="stat" id="stats"></span>
  </div>
</div>
<div class="content" id="timeline"></div>

<script>
const DATA = %%TIMELINE_DATA%%;

function monthName(m) {
  return parseInt(m) + '月';
}

function categoryBadge(cat) {
  const cls = {photo:'badge-photo',screenshot:'badge-screenshot',wechat:'badge-wechat',burst:'badge-burst',video:'badge-video'}[cat] || 'badge-photo';
  const label = {photo:'📷',screenshot:'📱',wechat:'💬',burst:'🔄',video:'🎬'}[cat] || '';
  return `<span class="badge ${cls}">${label}</span>`;
}

function qualityBadge(qs) {
  if (qs < 0) return '';
  const cls = qs >= 70 ? 'q-high' : (qs >= 40 ? 'q-mid' : 'q-low');
  return `<span class="quality-badge ${cls}">Q${qs}</span>`;
}

function eventTag(eid) {
  if (!eid || !DATA.events || !DATA.events[eid]) return '';
  const ev = DATA.events[eid];
  const colors = ['#667eea','#764ba2','#f093fb','#f5576c','#4facfe','#00f2fe','#43e97b','#fa709a','#feb47b'];
  const idx = Object.keys(DATA.events).indexOf(eid);
  const bg = colors[idx % colors.length];
  return `<span class="event-tag" style="background:${bg}" title="${ev.name}">${ev.name.split('(')[0].trim()}</span>`;
}

function populateEventFilter() {
  if (!DATA.events || !Object.keys(DATA.events).length) {
    document.getElementById('eventFilter').style.display = 'none';
    return;
  }
  const sel = document.getElementById('eventFilter');
  sel.innerHTML = '<option value="all">全部事件</option>';
  for (const [eid, ev] of Object.entries(DATA.events)) {
    sel.innerHTML += `<option value="${eid}">${ev.name} (${ev.photo_count})</option>`;
  }
}

function renderTimeline() {
  const cat = document.getElementById('category').value;
  const zoom = document.getElementById('zoom').value;
  const eventFilter = document.getElementById('eventFilter').value;
  const container = document.getElementById('timeline');
  let totalShown = 0;

  let html = '';
  for (const y of DATA.years) {
    let yearHtml = '';
    let yearShown = 0;

    // Track which events appear in this year for event banners
    let yearEvents = {};

    for (const m of y.months) {
      let monthHtml = '';
      let monthShown = 0;

      for (const d of m.days) {
        let photos = d.photos;
        if (cat !== 'all') photos = photos.filter(p => p.category === cat);
        if (eventFilter !== 'all') photos = photos.filter(p => p.event_id === eventFilter);
        if (photos.length === 0) continue;

        const dayLabel = `${parseInt(d.day)} ${monthName(m.month)}`;
        const dayPhotos = photos.map(p => {
          const thumb = p.thumb ? `<img src="data:image/jpeg;base64,${p.thumb}" alt="">` : `<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;font-size:10px;color:#86868b;">无预览</div>`;
          return `<div class="photo-thumb" title="${p.filename}\n${(p.camera_make||'')} ${(p.camera_model||'')}\n${p.size_str||''}">${thumb}${categoryBadge(p.category)}${qualityBadge(p.quality_score||-1)}${eventTag(p.event_id||'')}</div>`;
        }).join('');

        // Collect events for this day
        for (const p of photos) {
          if (p.event_id && DATA.events && DATA.events[p.event_id]) {
            yearEvents[p.event_id] = DATA.events[p.event_id];
          }
        }

        if (zoom === 'day') {
          monthHtml += `<div class="day-section"><div class="day-header">${dayLabel} (${photos.length})</div><div class="photo-grid">${dayPhotos}</div></div>`;
        }
        monthShown += photos.length;
      }

      if (monthShown === 0) continue;

      const monthLabel = `${monthName(m.month)} ${y.year}`;
      if (zoom === 'month' || zoom === 'year') {
        // Show sample thumbnails for the month
        let samplePhotos = [];
        for (const d of m.days) {
          let photos = d.photos;
          if (cat !== 'all') photos = photos.filter(p => p.category === cat);
          if (eventFilter !== 'all') photos = photos.filter(p => p.event_id === eventFilter);
          samplePhotos.push(...photos);
        }
        if (samplePhotos.length === 0) continue;
        const samples = samplePhotos.slice(0, 30).map(p => {
          const thumb = p.thumb ? `<img src="data:image/jpeg;base64,${p.thumb}" alt="">` : '';
          return `<div class="photo-thumb" title="${p.filename}">${thumb}${categoryBadge(p.category)}${qualityBadge(p.quality_score||-1)}${eventTag(p.event_id||'')}</div>`;
        }).join('');
        monthHtml = `<div class="photo-grid">${samples}</div>`;
      }

      const monthVis = zoom === 'year' ? 'style="display:none"' : '';
      yearHtml += `<div class="month-section" ${monthVis}><div class="month-header" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'"><span class="month-name">${monthLabel}</span><span class="month-count">${monthShown} 张</span></div>${monthHtml}</div>`;
      yearShown += monthShown;
    }

    if (yearShown === 0) continue;
    totalShown += yearShown;

    // Event banners for the year
    let eventHtml = '';
    if (Object.keys(yearEvents).length > 0 && zoom !== 'year') {
      for (const [eid, ev] of Object.entries(yearEvents)) {
        eventHtml += `<div class="event-banner"><span class="event-name">📍 ${ev.name}</span><span class="event-dates">${ev.start_date} ~ ${ev.end_date} · ${ev.photo_count} 张</span></div>`;
      }
    }

    html += `<div class="year-block">
      <div class="year-header" onclick="toggleYear(this)">
        <h2>${y.year}</h2>
        <span class="count">${yearShown} 张</span>
        <span class="toggle">▼</span>
      </div>
      ${eventHtml}
      ${yearHtml}
    </div>`;
  }

  if (!html) {
    html = '<div class="empty"><h3>未找到照片</h3><p>试试调整类别或事件筛选</p></div>';
  }
  container.innerHTML = html;
  document.getElementById('stats').textContent = `共 ${totalShown} 张`;
}

function toggleYear(el) {
  const sections = el.parentElement.querySelectorAll('.month-section');
  const hidden = sections.length > 0 && sections[0].style.display === 'none';
  sections.forEach(s => s.style.display = hidden ? 'block' : 'none');
  el.querySelector('.toggle').textContent = hidden ? '▼' : '▶';
}

function applyZoom() { renderTimeline(); }
function applyFilter() { renderTimeline(); }

function collapseAll() {
  document.querySelectorAll('.month-section').forEach(s => s.style.display = 'none');
  document.querySelectorAll('.toggle').forEach(t => t.textContent = '▶');
}

function expandAll() {
  document.querySelectorAll('.month-section').forEach(s => s.style.display = 'block');
  document.querySelectorAll('.toggle').forEach(t => t.textContent = '▼');
}

populateEventFilter();
renderTimeline();
</script>
</body>
</html>
"""


def generate_timeline_html(index_db: str, max_per_day: int = 0,
                           from_year: int = 0, to_year: int = 0,
                           max_thumbs: int = 2000) -> str:
    """Generate timeline HTML page."""
    # Load timeline structure
    timeline = build_timeline_data(index_db, max_per_day, from_year, to_year)

    # Load metadata for thumbnails
    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row
    metadata = {}
    for row in conn.execute("SELECT * FROM photos"):
        metadata[row["file_path"]] = dict(row)
    conn.close()

    # Add thumbnails and format data
    thumb_count = 0
    for year_data in timeline["years"]:
        for month_data in year_data["months"]:
            for day_data in month_data["days"]:
                for photo in day_data["photos"]:
                    path = photo.get("file_path", "")
                    meta = metadata.get(path, {})
                    # Add thumbnail (limited for performance)
                    if thumb_count < max_thumbs:
                        photo["thumb"] = get_thumbnail_base64(path, 100)
                        thumb_count += 1
                    else:
                        photo["thumb"] = ""
                    # Add display fields
                    photo["size_str"] = format_size(meta.get("size_bytes", 0) or 0)
                    photo["camera_make"] = meta.get("camera_make", "")
                    photo["camera_model"] = meta.get("camera_model", "")
                    photo["quality_score"] = int(meta.get("quality_score") or -1)
                    photo["event_id"] = meta.get("event_id") or ""

    data_json = json.dumps(timeline, ensure_ascii=False)
    return _HTML_TEMPLATE.replace("%%TIMELINE_DATA%%", data_json)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate interactive timeline view of photo library")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index")
    parser.add_argument("--output", "-o", dest="output", required=True,
                        help="Output HTML path")
    parser.add_argument("--max-per-day", type=int, default=0,
                        help="Max photos to show per day (0 = unlimited)")
    parser.add_argument("--max-thumbs", type=int, default=2000,
                        help="Max thumbnails to embed (0 = unlimited, may be slow)")
    parser.add_argument("--from-year", type=int, default=0,
                        help="Filter: start year (inclusive)")
    parser.add_argument("--to-year", type=int, default=0,
                        help="Filter: end year (inclusive)")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    index_path = os.path.abspath(args.index)
    output_path = os.path.abspath(args.output)

    print("📸 Generating timeline view...")
    html = generate_timeline_html(
        index_path,
        max_per_day=args.max_per_day,
        from_year=args.from_year,
        to_year=args.to_year,
        max_thumbs=args.max_thumbs,
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  Timeline saved: {output_path}")
    print(f"  Open in browser to explore your photo library chronologically.")


if __name__ == "__main__":
    main()
