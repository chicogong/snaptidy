#!/usr/bin/env python3
"""Generate an interactive review page for photo cleanup decisions.

Creates a self-contained HTML page where users can:
  1. Browse duplicate groups, screenshots, and orphan files
  2. See thumbnails + album + date + metadata completeness side-by-side
  3. Apply smart preference rules (keep most metadata, oldest, preferred album, etc.)
  4. Mark each photo as KEEP or REMOVE via radio buttons
  5. Export their decisions as a CSV for apply_move_plan.py

The page never touches files — it only records decisions.

Usage:
    python3 scripts/generate_review.py \
        --index photo_index.db \
        --duplicates duplicates.csv \
        --output review.html
"""

import argparse
import base64
import csv
import html
import json
import os
import sqlite3
import sys
from collections import defaultdict

from constants import format_size


def get_thumbnail_base64(path: str, max_size: int = 200) -> str:
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


def _load_groups(duplicates_csv: str) -> dict:
    """Load duplicate groups from CSV."""
    groups = defaultdict(list)
    with open(duplicates_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gid = row.get("group_id", "0")
            groups[gid].append(row)
    return groups


def _load_standalone_items(index_db: str) -> list:
    """Load standalone cleanup candidates (screenshots, no-EXIF, etc.)."""
    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row
    items = []

    # Screenshots
    cur = conn.execute(
        "SELECT * FROM photos WHERE category = 'screenshot' ORDER BY size_bytes DESC"
    )
    for row in cur:
        items.append(dict(row) | {"review_category": "screenshot"})

    # No EXIF (non-screenshot)
    cur = conn.execute(
        "SELECT * FROM photos WHERE (has_exif = 0 OR has_exif IS NULL) "
        "AND category != 'screenshot' ORDER BY size_bytes DESC LIMIT 50"
    )
    for row in cur:
        items.append(dict(row) | {"review_category": "no_exif"})

    conn.close()
    return items


def _calc_metadata_score(meta: dict) -> int:
    """Calculate metadata completeness score (0-100).

    Factors: has_exif, has_camera, has_gps, has_date, has_dimensions, is_favorite.
    """
    score = 0
    if meta.get("has_exif"):
        score += 20
    if meta.get("camera_make") or meta.get("camera_model"):
        score += 15
    if meta.get("gps_latitude") and meta.get("gps_longitude"):
        score += 15
    if meta.get("exif_datetime"):
        score += 15
    if meta.get("width") and meta.get("height"):
        score += 10
    if meta.get("photos_favorite"):
        score += 15
    if meta.get("place_city"):
        score += 10
    return score


def generate_review_html(index_db: str, duplicates_csv: str = None,
                         similar_csv: str = None, max_groups: int = 500) -> str:
    """Generate interactive review HTML page."""
    # Load metadata
    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row
    metadata = {}
    cursor = conn.execute("SELECT * FROM photos")
    for row in cursor:
        metadata[row["file_path"]] = dict(row)
    conn.close()

    # Load duplicate groups
    dup_groups = {}
    if duplicates_csv and os.path.exists(duplicates_csv):
        dup_groups = _load_groups(duplicates_csv)

    similar_groups = {}
    if similar_csv and os.path.exists(similar_csv):
        similar_groups = _load_groups(similar_csv)

    # Load standalone items
    standalone = _load_standalone_items(index_db)

    # Collect all unique album names for the preference selector
    all_albums = set()
    for meta in metadata.values():
        albums = meta.get("photos_albums", "")
        if albums:
            for a in albums.split(","):
                a = a.strip()
                if a:
                    all_albums.add(a)
    sorted_albums = sorted(all_albums)

    # Build JSON data for the page
    review_data = {"duplicate_groups": [], "similar_groups": [], "standalone": [], "all_albums": sorted_albums}

    # Duplicate groups
    for gid, members in sorted(dup_groups.items(), key=lambda x: int(x[0])):
        group = {"id": gid, "type": members[0].get("match_type", "exact"), "items": []}
        for m in members:
            path = m.get("file_path", "")
            meta = metadata.get(path, {})
            thumb = get_thumbnail_base64(path)
            group["items"].append({
                "path": path,
                "name": meta.get("filename", os.path.basename(path)),
                "size": meta.get("size_bytes", 0) or 0,
                "size_str": format_size(meta.get("size_bytes", 0) or 0),
                "width": meta.get("width", ""),
                "height": meta.get("height", ""),
                "category": meta.get("category", ""),
                "camera": (meta.get("camera_make", "") + " " + meta.get("camera_model", "")).strip(),
                "has_exif": bool(meta.get("has_exif", 0)),
                "date": meta.get("exif_datetime", ""),
                "place": meta.get("place_city", "") or "",
                "albums": meta.get("photos_albums", "") or "",
                "favorite": bool(meta.get("photos_favorite", 0)),
                "hidden": bool(meta.get("photos_hidden", 0)),
                "meta_score": _calc_metadata_score(meta),
                "quality_score": int(meta.get("quality_score") or -1),
                "is_animated": bool(meta.get("is_animated", 0)),
                "orientation": int(meta.get("orientation") or 1),
                "thumb": thumb,
            })
        review_data["duplicate_groups"].append(group)

    # Similar groups
    for gid, members in sorted(similar_groups.items(), key=lambda x: int(x[0])):
        group = {"id": gid, "type": members[0].get("match_type", "similar"), "items": []}
        for m in members:
            path = m.get("file_path", "")
            meta = metadata.get(path, {})
            thumb = get_thumbnail_base64(path)
            group["items"].append({
                "path": path,
                "name": meta.get("filename", os.path.basename(path)),
                "size": meta.get("size_bytes", 0) or 0,
                "size_str": format_size(meta.get("size_bytes", 0) or 0),
                "width": meta.get("width", ""),
                "height": meta.get("height", ""),
                "category": meta.get("category", ""),
                "camera": (meta.get("camera_make", "") + " " + meta.get("camera_model", "")).strip(),
                "has_exif": bool(meta.get("has_exif", 0)),
                "date": meta.get("exif_datetime", ""),
                "place": meta.get("place_city", "") or "",
                "albums": meta.get("photos_albums", "") or "",
                "favorite": bool(meta.get("photos_favorite", 0)),
                "hidden": bool(meta.get("photos_hidden", 0)),
                "meta_score": _calc_metadata_score(meta),
                "quality_score": int(meta.get("quality_score") or -1),
                "is_animated": bool(meta.get("is_animated", 0)),
                "orientation": int(meta.get("orientation") or 1),
                "thumb": thumb,
            })
        review_data["similar_groups"].append(group)

    # Standalone items
    for item in standalone:
        path = item.get("file_path", "")
        thumb = get_thumbnail_base64(path)
        review_data["standalone"].append({
            "path": path,
            "name": item.get("filename", os.path.basename(path)),
            "size": item.get("size_bytes", 0) or 0,
            "size_str": format_size(item.get("size_bytes", 0) or 0),
            "width": item.get("width", ""),
            "height": item.get("height", ""),
            "category": item.get("category", ""),
            "camera": (item.get("camera_make", "") + " " + item.get("camera_model", "")).strip(),
            "has_exif": bool(item.get("has_exif", 0)),
            "date": item.get("exif_datetime", ""),
            "place": item.get("place_city", "") or "",
            "albums": item.get("photos_albums", "") or "",
            "favorite": bool(item.get("photos_favorite", 0)),
            "hidden": bool(item.get("photos_hidden", 0)),
            "meta_score": _calc_metadata_score(item),
            "quality_score": int(item.get("quality_score") or -1),
            "is_animated": bool(item.get("is_animated", 0)),
            "orientation": int(item.get("orientation") or 1),
            "thumb": thumb,
            "review_category": item.get("review_category", ""),
        })

    # Inject data into HTML
    data_json = json.dumps(review_data, ensure_ascii=False)

    return _HTML_TEMPLATE.replace("%%REVIEW_DATA%%", data_json)


# ---------------------------------------------------------------------------
# HTML template — self-contained, no external deps
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SnapTidy — 照片审核</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
       background: #f5f5f7; color: #1d1d1f; }
.header { background: white; border-bottom: 1px solid #e8e8ed; padding: 14px 24px;
           position: sticky; top: 0; z-index: 100; }
.header-top { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.header h1 { font-size: 18px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.btn { padding: 7px 14px; border-radius: 8px; border: none; font-size: 12px;
       font-weight: 500; cursor: pointer; transition: all 0.15s; white-space: nowrap; }
.btn-primary { background: #007aff; color: white; }
.btn-primary:hover { background: #0066d6; }
.btn-secondary { background: #e8e8ed; color: #1d1d1f; }
.btn-secondary:hover { background: #d1d1d6; }
.btn-danger { background: #ff3b30; color: white; }
.btn-danger:hover { background: #d63028; }
.btn-success { background: #34c759; color: white; }
.btn-success:hover { background: #28a745; }
.counter { font-size: 12px; color: #86868b; }
.counter strong { color: #ff3b30; }

/* Strategy bar */
.strategy-bar { display: flex; align-items: center; gap: 12px; margin-top: 10px;
                padding: 10px 16px; background: #f5f5f7; border-radius: 8px; flex-wrap: wrap; }
.strategy-bar label { font-size: 12px; font-weight: 500; color: #48484a; white-space: nowrap; }
.strategy-bar select { padding: 5px 10px; border-radius: 6px; border: 1px solid #d1d1d6;
                      font-size: 12px; background: white; min-width: 160px; }
.strategy-bar .pref-group { display: flex; align-items: center; gap: 6px; }

.content { max-width: 1400px; margin: 0 auto; padding: 20px; padding-bottom: 80px; }

/* Tabs */
.tabs { display: flex; gap: 0; background: white; border-radius: 10px;
        margin-bottom: 20px; overflow: hidden; border: 1px solid #e8e8ed; }
.tab { flex: 1; padding: 12px 16px; text-align: center; cursor: pointer;
       font-size: 13px; font-weight: 500; color: #86868b; border-bottom: 2px solid transparent;
       transition: all 0.15s; }
.tab:hover { color: #1d1d1f; background: #f5f5f7; }
.tab.active { color: #007aff; border-bottom-color: #007aff; background: white; }
.tab .tab-count { display: inline-block; background: #e8e8ed; color: #48484a;
                  padding: 1px 7px; border-radius: 10px; font-size: 11px; margin-left: 4px; }
.tab.active .tab-count { background: #d1e4ff; color: #007aff; }

/* Group card */
.group { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px;
         box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.group-header { display: flex; justify-content: space-between; align-items: center;
                margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
.group-id { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.group-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.group-btn { padding: 4px 10px; border-radius: 6px; font-size: 11px; cursor: pointer;
             border: 1px solid #e8e8ed; background: white; color: #48484a; transition: all 0.15s; }
.group-btn:hover { background: #f5f5f7; }
.group-btn.all-remove { border-color: #ff3b30; color: #ff3b30; }
.group-btn.all-remove:hover { background: #fff0f0; }
.group-btn.smart-pick { border-color: #007aff; color: #007aff; }
.group-btn.smart-pick:hover { background: #eef5ff; }

.match-badge { padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 500;
               background: #e8e8ed; color: #48484a; }

/* Comparison table */
.compare-table { width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 12px; }
.compare-table th { text-align: left; padding: 6px 10px; background: #f5f5f7; font-weight: 500;
                    color: #86868b; border-bottom: 1px solid #e8e8ed; white-space: nowrap; }
.compare-table td { padding: 6px 10px; border-bottom: 1px solid #f0f0f0; vertical-align: middle; }
.compare-table tr.best td { background: #f0fdf4; }
.compare-table tr.worst td { background: #fff5f5; }

.cards { display: flex; gap: 12px; flex-wrap: wrap; }

/* Photo card */
.card { border: 2px solid #e8e8ed; border-radius: 10px; padding: 12px; min-width: 200px;
        max-width: 260px; position: relative; transition: border-color 0.15s, background 0.15s; }
.card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.card.keep { border-color: #34c759; background: #f0fdf4; }
.card.remove { border-color: #ff3b30; background: #fff5f5; }
.card.best-pick { box-shadow: 0 0 0 2px #007aff; }
.card-label { position: absolute; top: 8px; left: 8px; z-index: 2; display: flex; gap: 2px; }
.card-label input[type="radio"] { display: none; }
.card-label span { display: inline-block; padding: 2px 8px; border-radius: 4px;
                   font-size: 10px; font-weight: 600; cursor: pointer; border: 1px solid; }
.card-label .opt-keep { border-color: #34c759; color: #34c759; background: white; }
.card-label .opt-remove { border-color: #ff3b30; color: #ff3b30; background: white; }
.card.keep .card-label .opt-keep { background: #34c759; color: white; }
.card.remove .card-label .opt-remove { background: #ff3b30; color: white; }
.thumbnail { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px;
             background: #f0f0f0; margin-bottom: 8px; }
.no-thumb { display: flex; align-items: center; justify-content: center;
            width: 100%; aspect-ratio: 1; background: #f5f5f7; border-radius: 6px;
            color: #86868b; font-size: 12px; margin-bottom: 8px; }
.meta { font-size: 11px; color: #86868b; line-height: 1.6; }
.meta strong { color: #1d1d1f; }
.fname { font-size: 12px; font-weight: 500; white-space: nowrap; overflow: hidden;
         text-overflow: ellipsis; margin-bottom: 4px; max-width: 220px; }
.album-tag { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px;
             margin: 1px 2px 1px 0; background: #e8e8ed; color: #48484a; }
.album-tag.preferred { background: #d1e4ff; color: #007aff; }
.score-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px;
               font-weight: 600; }
.score-high { background: #d1faf0; color: #00a86b; }
.score-mid { background: #fff8e1; color: #b8860b; }
.score-low { background: #fff0f0; color: #ff3b30; }
.fav-badge { color: #ff9500; font-size: 12px; }

/* Standalone items */
.standalone-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
                   gap: 12px; }
.mini-card { border: 2px solid #e8e8ed; border-radius: 10px; padding: 10px;
             position: relative; transition: border-color 0.15s; }
.mini-card.remove { border-color: #ff3b30; background: #fff5f5; }
.mini-card.keep { border-color: #34c759; background: #f0fdf4; }
.mini-check { position: absolute; top: 8px; right: 8px; }

/* Footer bar */
.footer-bar { position: fixed; bottom: 0; left: 0; right: 0; background: white;
              border-top: 1px solid #e8e8ed; padding: 12px 24px; z-index: 100;
              display: flex; align-items: center; justify-content: space-between; }
.progress-text { font-size: 12px; color: #86868b; }
.progress-text strong { color: #1d1d1f; }
.space-bar { width: 200px; height: 6px; background: #e8e8ed; border-radius: 3px; overflow: hidden; }
.space-fill { height: 100%; background: #ff3b30; border-radius: 3px; transition: width 0.3s; }

/* Empty state */
.empty { text-align: center; padding: 60px 20px; color: #86868b; }
.empty-icon { font-size: 48px; margin-bottom: 12px; }

/* Dark mode */
@media (prefers-color-scheme: dark) {
  body { background: #1c1c1e; color: #e5e5e7; }
  .header { background: #2c2c2e; border-bottom-color: #38383a; }
  .btn-secondary { background: #3a3a3c; color: #e5e5e7; }
  .btn-secondary:hover { background: #48484a; }
  .strategy-bar { background: #1c1c1e; }
  .strategy-bar label { color: #98989d; }
  .strategy-bar select { background: #2c2c2e; border-color: #48484a; color: #e5e5e7; }
  .tabs { background: #2c2c2e; border-color: #38383a; }
  .tab { color: #98989d; }
  .tab:hover { background: #3a3a3c; color: #e5e5e7; }
  .tab.active { background: #2c2c2e; }
  .tab .tab-count { background: #3a3a3c; color: #98989d; }
  .tab.active .tab-count { background: #0a3d6e; color: #4da2ff; }
  .group { background: #2c2c2e; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
  .group-btn { border-color: #38383a; background: #2c2c2e; color: #c7c7cc; }
  .group-btn:hover { background: #3a3a3c; }
  .group-btn.all-remove:hover { background: #3a1a1a; }
  .group-btn.smart-pick:hover { background: #1a2a3a; }
  .match-badge { background: #3a3a3c; color: #c7c7cc; }
  .compare-table th { background: #1c1c1e; border-bottom-color: #38383a; }
  .compare-table td { border-bottom-color: #2c2c2e; }
  .compare-table tr.best td { background: #1a2e1e; }
  .compare-table tr.worst td { background: #2e1a1a; }
  .card { border-color: #38383a; }
  .card.keep { border-color: #34c759; background: #1a2e1e; }
  .card.remove { border-color: #ff3b30; background: #2e1a1a; }
  .card-label .opt-keep { background: #2c2c2e; }
  .card-label .opt-remove { background: #2c2c2e; }
  .thumbnail { background: #3a3a3c; }
  .no-thumb { background: #3a3a3c; color: #636366; }
  .meta { color: #98989d; }
  .meta strong { color: #e5e5e7; }
  .fname { color: #e5e5e7; }
  .album-tag { background: #3a3a3c; color: #c7c7cc; }
  .album-tag.preferred { background: #0a3d6e; color: #4da2ff; }
  .score-high { background: #1a2e1e; }
  .score-mid { background: #2e2a1a; }
  .score-low { background: #2e1a1a; }
  .mini-card { border-color: #38383a; }
  .mini-card.remove { background: #2e1a1a; }
  .mini-card.keep { background: #1a2e1e; }
  .footer-bar { background: #2c2c2e; border-top-color: #38383a; }
  .progress-text { color: #98989d; }
  .progress-text strong { color: #e5e5e7; }
  .space-bar { background: #3a3a3c; }
  .empty { color: #636366; }
}

/* Responsive */
@media (max-width: 768px) {
  .header { padding: 10px 12px; }
  .header-top { flex-direction: column; align-items: flex-start; gap: 8px; }
  .header-actions { width: 100%; }
  .strategy-bar { flex-direction: column; align-items: flex-start; gap: 8px; }
  .strategy-bar select { min-width: 140px; width: 100%; }
  .content { padding: 12px; padding-bottom: 100px; }
  .tabs { flex-direction: column; border-radius: 8px; }
  .tab { padding: 10px 12px; border-bottom: 1px solid #e8e8ed; }
  .tab.active { border-bottom-color: #007aff; }
  .cards { flex-direction: column; }
  .card { min-width: 100%; max-width: 100%; }
  .compare-table { font-size: 11px; }
  .footer-bar { flex-direction: column; gap: 8px; padding: 10px 12px; }
  .space-bar { width: 100%; }
  .standalone-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
}
@media (max-width: 480px) {
  .hero h1 { font-size: 14px; }
  .btn { font-size: 11px; padding: 6px 10px; }
  .group { padding: 12px; }
  .compare-table th, .compare-table td { padding: 4px 6px; }
}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <h1>SnapTidy 照片审核</h1>
    <div class="header-actions">
      <span class="counter">标记删除: <strong id="remove-count">0</strong> 张</span>
      <span class="counter" style="opacity:0.6">⌨️ ←→切换 K智能 R删除 A保留 1/2/3标签 E导出</span>
      <button class="btn btn-primary" onclick="exportCSV()">导出决策 CSV</button>
    </div>
  </div>
  <div class="strategy-bar">
    <label>智能策略:</label>
    <select id="strategy" onchange="applySmartRules()">
      <option value="most_metadata">保留元数据最全的</option>
      <option value="best_quality">保留画质最好的</option>
      <option value="oldest">保留日期最早的</option>
      <option value="newest">保留日期最新的</option>
      <option value="largest">保留分辨率最高的</option>
      <option value="preferred_album">保留指定相册的</option>
    </select>
    <div class="pref-group" id="album-pref-group" style="display:none;">
      <label>优先相册:</label>
      <select id="preferred-album" onchange="applySmartRules()">
        <option value="">-- 选择相册 --</option>
      </select>
    </div>
    <button class="btn btn-secondary" onclick="applySmartRules()">应用策略</button>
    <button class="btn btn-secondary" onclick="resetAll()">重置</button>
  </div>
</div>

<div class="content">
  <div class="tabs" id="tabs">
    <div class="tab active" data-tab="duplicates" onclick="switchTab('duplicates')">
      精确重复 <span class="tab-count" id="dup-count">0</span>
    </div>
    <div class="tab" data-tab="similar" onclick="switchTab('similar')">
      相似图片 <span class="tab-count" id="sim-count">0</span>
    </div>
    <div class="tab" data-tab="standalone" onclick="switchTab('standalone')">
      截图/无EXIF <span class="tab-count" id="standalone-count">0</span>
    </div>
  </div>

  <div id="tab-duplicates"></div>
  <div id="tab-similar" style="display:none"></div>
  <div id="tab-standalone" style="display:none"></div>
</div>

<div class="footer-bar">
  <div>
    <div class="progress-text">
      已审核 <strong id="reviewed-count">0</strong> / <strong id="total-count">0</strong> 组
      &nbsp;|&nbsp; 已决策 <strong id="decided-count">0</strong> 张
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:12px;">
    <span class="progress-text">可释放: <strong id="reclaim-size">0 KB</strong></span>
    <div class="space-bar"><div class="space-fill" id="space-fill" style="width:0%"></div></div>
  </div>
</div>

<script>
const DATA = %%REVIEW_DATA%%;

// Decision store: path -> "keep" | "remove"
const decisions = {};

// Strategy toggle
document.getElementById('strategy').addEventListener('change', function() {
  document.getElementById('album-pref-group').style.display =
    this.value === 'preferred_album' ? 'flex' : 'none';
  applySmartRules();
});

// Populate album dropdown
(function() {
  const sel = document.getElementById('preferred-album');
  for (const album of DATA.all_albums) {
    const opt = document.createElement('option');
    opt.value = album;
    opt.textContent = album;
    sel.appendChild(opt);
  }
})();

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1048576).toFixed(1) + ' MB';
}

function scoreBadge(score) {
  const cls = score >= 60 ? 'score-high' : (score >= 30 ? 'score-mid' : 'score-low');
  return `<span class="score-badge ${cls}">${score}分</span>`;
}

function qualityBadge(qs) {
  const cls = qs >= 70 ? 'score-high' : (qs >= 40 ? 'score-mid' : 'score-low');
  return `<span class="score-badge ${cls}">Q${qs}</span>`;
}

function albumTags(albumsStr, preferredAlbum) {
  if (!albumsStr) return '<span style="color:#c7c7cc;">无相册</span>';
  const albums = albumsStr.split(',').map(a => a.trim()).filter(a => a);
  return albums.map(a => {
    const isPref = preferredAlbum && a === preferredAlbum;
    return `<span class="album-tag${isPref ? ' preferred' : ''}">${a.replace(/</g,'&lt;')}</span>`;
  }).join('');
}

function setDecision(path, decision) {
  decisions[path] = decision;
  updateUI();
}

function updateUI() {
  let removeCount = 0;
  let removeSize = 0;
  let decidedCount = 0;

  const allItems = [...DATA.duplicate_groups, ...DATA.similar_groups].flatMap(g => g.items)
    .concat(DATA.standalone);
  const sizeMap = {};
  for (const item of allItems) {
    sizeMap[item.path] = item.size;
  }

  for (const [path, dec] of Object.entries(decisions)) {
    decidedCount++;
    if (dec === 'remove') {
      removeCount++;
      removeSize += (sizeMap[path] || 0);
    }
  }

  document.getElementById('remove-count').textContent = removeCount;
  document.getElementById('reclaim-size').textContent = formatSize(removeSize);
  document.getElementById('decided-count').textContent = decidedCount;

  const totalGroups = DATA.duplicate_groups.length + DATA.similar_groups.length
    + (DATA.standalone.length > 0 ? 1 : 0);
  const reviewed = new Set();
  for (const g of [...DATA.duplicate_groups, ...DATA.similar_groups]) {
    const allDecided = g.items.every(i => decisions[i.path]);
    if (allDecided) reviewed.add(g.id);
  }
  if (DATA.standalone.length > 0) {
    const allDecided = DATA.standalone.every(i => decisions[i.path]);
    if (allDecided) reviewed.add('standalone');
  }
  document.getElementById('reviewed-count').textContent = [...reviewed].length;
  document.getElementById('total-count').textContent = totalGroups;

  // Update card visuals
  document.querySelectorAll('.card').forEach(card => {
    const path = card.dataset.path;
    const dec = decisions[path] || '';
    card.classList.remove('keep', 'remove');
    if (dec === 'keep') card.classList.add('keep');
    else if (dec === 'remove') card.classList.add('remove');
  });
  document.querySelectorAll('.mini-card').forEach(card => {
    const path = card.dataset.path;
    const dec = decisions[path] || '';
    card.classList.remove('keep', 'remove');
    if (dec === 'keep') card.classList.add('keep');
    else if (dec === 'remove') card.classList.add('remove');
  });

  // Update radio buttons
  document.querySelectorAll('.card-label input').forEach(radio => {
    const path = radio.dataset.path;
    radio.checked = (radio.value === decisions[path]);
  });
  document.querySelectorAll('.mini-check input').forEach(cb => {
    const path = cb.dataset.path;
    cb.checked = (decisions[path] === 'remove');
  });

  // Space bar
  const totalSize = allItems.reduce((s, i) => s + (i.size || 0), 0);
  const pct = totalSize > 0 ? (removeSize / totalSize * 100) : 0;
  document.getElementById('space-fill').style.width = pct + '%';
}

// --- Smart Rule Engine ---

function pickBest(items, strategy) {
  // Pick the single best item to KEEP based on strategy. Returns index.
  if (items.length === 0) return -1;

  // Always protect favorites
  const favorites = items.filter(i => i.favorite);
  if (favorites.length === 1) return items.indexOf(favorites[0]);
  if (favorites.length > 1) {
    // Multiple favorites, apply strategy among them
    return items.indexOf(pickBestByStrategy(favorites, strategy));
  }

  return items.indexOf(pickBestByStrategy(items, strategy));
}

function pickBestByStrategy(items, strategy) {
  let best = items[0];
  const preferredAlbum = document.getElementById('preferred-album').value;

  for (const item of items) {
    switch (strategy) {
      case 'most_metadata':
        if (item.meta_score > best.meta_score) best = item;
        else if (item.meta_score === best.meta_score && item.size > best.size) best = item;
        break;
      case 'best_quality':
        if (item.quality_score >= 0 && best.quality_score < 0) best = item;
        else if (item.quality_score >= 0 && best.quality_score >= 0 && item.quality_score > best.quality_score) best = item;
        else if (item.quality_score === best.quality_score && item.meta_score > best.meta_score) best = item;
        break;
      case 'oldest':
        if (item.date && (!best.date || item.date < best.date)) best = item;
        else if (item.date === best.date && item.meta_score > best.meta_score) best = item;
        break;
      case 'newest':
        if (item.date && (!best.date || item.date > best.date)) best = item;
        else if (item.date === best.date && item.meta_score > best.meta_score) best = item;
        break;
      case 'largest':
        const aPixels = (parseInt(item.width)||0) * (parseInt(item.height)||0);
        const bPixels = (parseInt(best.width)||0) * (parseInt(best.height)||0);
        if (aPixels > bPixels) best = item;
        else if (aPixels === bPixels && item.meta_score > best.meta_score) best = item;
        break;
      case 'preferred_album':
        if (preferredAlbum) {
          const aHas = (item.albums || '').includes(preferredAlbum);
          const bHas = (best.albums || '').includes(preferredAlbum);
          if (aHas && !bHas) { best = item; }
          else if (aHas === bHas && item.meta_score > best.meta_score) best = item;
        } else {
          // No album selected, fall back to most_metadata
          if (item.meta_score > best.meta_score) best = item;
        }
        break;
    }
  }
  return best;
}

function applySmartRules() {
  const strategy = document.getElementById('strategy').value;
  const groups = [...DATA.duplicate_groups, ...DATA.similar_groups];

  for (const g of groups) {
    if (g.items.length <= 1) continue;
    const bestIdx = pickBest(g.items, strategy);
    for (let i = 0; i < g.items.length; i++) {
      decisions[g.items[i].path] = (i === bestIdx) ? 'keep' : 'remove';
    }
  }

  // Standalone: keep all by default (user decides individually)
  for (const item of DATA.standalone) {
    if (!decisions[item.path]) {
      decisions[item.path] = item.review_category === 'screenshot' ? 'remove' : 'keep';
    }
  }

  updateUI();
  highlightBestPicks();
}

function highlightBestPicks() {
  const strategy = document.getElementById('strategy').value;
  document.querySelectorAll('.card.best-pick').forEach(c => c.classList.remove('best-pick'));

  for (const g of [...DATA.duplicate_groups, ...DATA.similar_groups]) {
    if (g.items.length <= 1) continue;
    const bestIdx = pickBest(g.items, strategy);
    const bestPath = g.items[bestIdx].path;
    document.querySelectorAll(`.card[data-path="${CSS.escape(bestPath)}"]`).forEach(c => {
      c.classList.add('best-pick');
    });
  }
}

function resetAll() {
  for (const key of Object.keys(decisions)) {
    delete decisions[key];
  }
  document.querySelectorAll('.card.best-pick').forEach(c => c.classList.remove('best-pick'));
  updateUI();
}

function setGroupAll(gid, decision) {
  const groups = [...DATA.duplicate_groups, ...DATA.similar_groups];
  const g = groups.find(g => g.id === gid);
  if (g) {
    for (const item of g.items) {
      decisions[item.path] = decision;
    }
  }
  updateUI();
}

function setGroupSmart(gid) {
  const strategy = document.getElementById('strategy').value;
  const groups = [...DATA.duplicate_groups, ...DATA.similar_groups];
  const g = groups.find(g => g.id === gid);
  if (!g || g.items.length <= 1) return;
  const bestIdx = pickBest(g.items, strategy);
  for (let i = 0; i < g.items.length; i++) {
    decisions[g.items[i].path] = (i === bestIdx) ? 'keep' : 'remove';
  }
  updateUI();
}

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector(`.tab[data-tab="${tab}"]`).classList.add('active');
  document.getElementById('tab-duplicates').style.display = tab === 'duplicates' ? '' : 'none';
  document.getElementById('tab-similar').style.display = tab === 'similar' ? '' : 'none';
  document.getElementById('tab-standalone').style.display = tab === 'standalone' ? '' : 'none';
}

function exportCSV() {
  const rows = [];
  for (const [path, dec] of Object.entries(decisions)) {
    if (dec === 'remove') {
      rows.push({ action: 'trash', source_path: path, reason: 'user_reviewed' });
    }
  }
  if (rows.length === 0) {
    alert('没有标记任何照片为删除，请先审核。');
    return;
  }
  const csvContent = '\uFEFFaction,source_path,reason\n' +
    rows.map(r => `${r.action},${JSON.stringify(r.source_path)},${r.reason}`).join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'snaptidy_review_decisions.csv';
  a.click();
  URL.revokeObjectURL(url);
}

// --- Render ---

function renderPhotoCard(item, gid, preferredAlbum) {
  const thumb = item.thumb
    ? `<img class="thumbnail" src="data:image/jpeg;base64,${item.thumb}" alt="">`
    : `<div class="no-thumb">No preview</div>`;
  const name = item.name || item.path.split('/').pop();
  const escName = name.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const dateStr = item.date ? item.date.substring(0, 19).replace('T', ' ') : '<span style="color:#c7c7cc">无日期</span>';
  const placeStr = item.place ? ` &middot; ${item.place.replace(/</g,'&lt;')}` : '';
  const favStar = item.favorite ? ' <span class="fav-badge">\u2B50</span>' : '';
  const animatedBadge = item.is_animated ? ' <span style="font-size:11px;color:#FF9500;" title="Animated (GIF/WebP/APNG)">🎬</span>' : '';
  const rotationBadge = (item.orientation > 1) ? ` <span style="font-size:11px;color:#FF9500;" title="EXIF rotation: ${item.orientation}">🔄</span>` : '';
  const escPath = item.path.replace(/"/g, '&quot;');
  const radioName = `dec-${gid}-${item.path.replace(/[^a-zA-Z0-9]/g,'X')}`;

  return `
    <div class="card" data-path="${escPath}">
      <div class="card-label">
        <label><input type="radio" name="${radioName}" value="keep"
               data-path="${escPath}"
               onchange="setDecision(this.dataset.path,'keep')"><span class="opt-keep">保留</span></label>
        <label><input type="radio" name="${radioName}" value="remove"
               data-path="${escPath}"
               onchange="setDecision(this.dataset.path,'remove')"><span class="opt-remove">删除</span></label>
      </div>
      ${thumb}
      <div class="fname" title="${escName}">${escName}${favStar}${animatedBadge}${rotationBadge}</div>
      <div class="meta">
        ${albumTags(item.albums, preferredAlbum)}<br>
        <strong>${item.width || '?'}x${item.height || '?'}</strong> &middot; ${item.size_str}${placeStr}<br>
        ${dateStr} &middot; ${item.camera ? item.camera.replace(/</g,'&lt;') : '<span style="color:#c7c7cc">无相机</span>'}<br>
        EXIF: ${item.has_exif ? 'Yes' : '<span style="color:#ff3b30">No</span>'}
        &middot; 元数据: ${scoreBadge(item.meta_score)}
        ${item.quality_score >= 0 ? '&middot; 质量: ' + qualityBadge(item.quality_score) : ''}
      </div>
    </div>`;
}

function renderGroups(groups, containerId) {
  const container = document.getElementById(containerId);
  if (!groups.length) {
    container.innerHTML = '<div class="empty"><div class="empty-icon">&#x1F389;</div><p>没有检测到该类型项目</p></div>';
    return;
  }
  const preferredAlbum = document.getElementById('preferred-album').value;
  let html = '';
  for (const g of groups) {
    const typeLabels = {
      'exact_sha256':'SHA-256 精确重复','exact_phash':'pHash 精确匹配',
      'fuzzy_phash':'pHash 相似','scaled':'缩放重复','cross_format':'跨格式重复',
      'burst_subsec':'连拍','apple_quality_vector':'Apple QL 相似','similar':'相似图片'
    };
    const typeLabel = typeLabels[g.type] || g.type || '相似图片';
    const itemCount = g.items.length;
    const totalSize = g.items.reduce((s,i) => s + i.size, 0);

    // Compute best pick for this group
    const strategy = document.getElementById('strategy').value;
    const bestIdx = pickBest(g.items, strategy);
    const bestMeta = bestIdx >= 0 ? g.items[bestIdx] : null;

    html += `<div class="group">
      <div class="group-header">
        <span class="group-id">
          Group ${g.id} <span class="match-badge">${typeLabel}</span>
          <span style="font-size:11px;color:#86868b;">(${itemCount}张, ${formatSize(totalSize)})</span>
        </span>
        <div class="group-actions">
          <button class="group-btn smart-pick" onclick="setGroupSmart('${g.id}')">智能选择</button>
          <button class="group-btn" onclick="setGroupAll('${g.id}','keep')">全部保留</button>
          <button class="group-btn all-remove" onclick="setGroupAll('${g.id}','remove')">全部删除</button>
        </div>
      </div>
      <div class="cards">
        ${g.items.map(i => renderPhotoCard(i, g.id, preferredAlbum)).join('')}
      </div>
    </div>`;
  }
  container.innerHTML = html;
}

function renderStandalone(items, containerId) {
  const container = document.getElementById(containerId);
  if (!items.length) {
    container.innerHTML = '<div class="empty"><div class="empty-icon">&#x2705;</div><p>没有截图或无EXIF的照片</p></div>';
    return;
  }
  let html = '<div class="standalone-grid">';
  for (const item of items) {
    const thumb = item.thumb
      ? `<img class="thumbnail" src="data:image/jpeg;base64,${item.thumb}" alt="" style="width:100%;aspect-ratio:1;object-fit:cover;border-radius:6px;background:#f0f0f0;margin-bottom:6px;">`
      : `<div class="no-thumb" style="margin-bottom:6px;">No preview</div>`;
    const name = item.name || item.path.split('/').pop();
    const escName = name.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const badge = item.review_category === 'screenshot' ? '📱截图' : '⚠️无EXIF';
    const dateStr = item.date ? item.date.substring(0, 10) : '';
    const escPath = item.path.replace(/"/g,'&quot;');
    html += `<div class="mini-card" data-path="${escPath}">
      <div class="mini-check">
        <input type="checkbox" data-path="${escPath}"
               onchange="setDecision(this.dataset.path, this.checked?'remove':'keep')">
      </div>
      ${thumb}
      <div class="fname" style="font-size:11px;">${escName}</div>
      <div class="meta" style="font-size:10px;">${badge} &middot; ${item.size_str}${dateStr ? ' &middot; '+dateStr : ''}</div>
      <div style="font-size:9px;margin-top:2px;">${albumTags(item.albums, '')}</div>
    </div>`;
  }
  html += '</div>';
  container.innerHTML = html;
}

// Init
document.getElementById('dup-count').textContent = DATA.duplicate_groups.length;
document.getElementById('sim-count').textContent = DATA.similar_groups.length;
document.getElementById('standalone-count').textContent = DATA.standalone.length;

renderGroups(DATA.duplicate_groups, 'tab-duplicates');
renderGroups(DATA.similar_groups, 'tab-similar');
renderStandalone(DATA.standalone, 'tab-standalone');

// Auto-apply smart rules on load
applySmartRules();
updateUI();

// --- Keyboard Shortcuts ---
let currentGroupIdx = 0;

function getVisibleGroups() {
  return [...document.querySelectorAll('.group')];
}

function scrollToGroup(idx) {
  const groups = getVisibleGroups();
  if (!groups.length) return;
  idx = Math.max(0, Math.min(idx, groups.length - 1));
  currentGroupIdx = idx;
  groups.forEach((g, i) => {
    if (i === idx) g.style.outline = '2px solid #007aff';
    else g.style.outline = '';
  });
  groups[idx].scrollIntoView({ behavior: 'smooth', block: 'center' });
}

document.addEventListener('keydown', function(e) {
  // Don't interfere with form inputs
  const tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;

  const groups = getVisibleGroups();

  switch(e.key) {
    case 'ArrowRight':
    case 'ArrowDown':
      e.preventDefault();
      scrollToGroup(currentGroupIdx + 1);
      break;
    case 'ArrowLeft':
    case 'ArrowUp':
      e.preventDefault();
      scrollToGroup(currentGroupIdx - 1);
      break;
    case 'k':
    case 'K': {
      e.preventDefault();
      const g = groups[currentGroupIdx];
      if (g) {
        const gid = g.querySelector('.group-id')?.textContent?.match(/Group (\d+)/)?.[1];
        if (gid) setGroupSmart(gid);
      }
      break;
    }
    case 'r':
    case 'R': {
      e.preventDefault();
      const g = groups[currentGroupIdx];
      if (g) {
        const gid = g.querySelector('.group-id')?.textContent?.match(/Group (\d+)/)?.[1];
        if (gid) setGroupAll(gid, 'remove');
      }
      break;
    }
    case 'a':
    case 'A': {
      e.preventDefault();
      const g = groups[currentGroupIdx];
      if (g) {
        const gid = g.querySelector('.group-id')?.textContent?.match(/Group (\d+)/)?.[1];
        if (gid) setGroupAll(gid, 'keep');
      }
      break;
    }
    case '1':
      e.preventDefault();
      switchTab('duplicates');
      scrollToGroup(0);
      break;
    case '2':
      e.preventDefault();
      switchTab('similar');
      scrollToGroup(0);
      break;
    case '3':
      e.preventDefault();
      switchTab('standalone');
      break;
    case 'e':
    case 'E':
      e.preventDefault();
      exportCSV();
      break;
  }
});
</script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate interactive HTML review page for photo cleanup decisions")
    parser.add_argument("--index", "-i", required=True, help="SQLite metadata index")
    parser.add_argument("--duplicates", default="", help="Exact duplicates CSV")
    parser.add_argument("--similar", default="", help="Similar photos CSV")
    parser.add_argument("--output", "--report", "-o", dest="output", required=True,
                        help="Output HTML file path")
    parser.add_argument("--max-groups", type=int, default=500,
                        help="Maximum groups to render (default: 500)")
    args = parser.parse_args()

    html_out = generate_review_html(
        os.path.abspath(args.index),
        os.path.abspath(args.duplicates) if args.duplicates else None,
        os.path.abspath(args.similar) if args.similar else None,
        max_groups=args.max_groups,
    )

    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"Review page generated: {output_path}")
    print(f"  Open in browser: file://{output_path}")
    print()
    print("Workflow:")
    print("  1. 打开页面，选择智能策略或逐组审核")
    print("  2. 点击「应用策略」一键标记，或逐张选择保留/删除")
    print("  3. 点击「导出决策 CSV」下载决策文件")
    print("  4. 使用 apply_move_plan.py --plan decisions.csv 执行")


if __name__ == "__main__":
    main()
