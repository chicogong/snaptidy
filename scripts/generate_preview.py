#!/usr/bin/env python3
"""Generate an HTML preview page with thumbnails for duplicate groups.

Creates a visual, interactive HTML page where users can inspect duplicate
groups before confirming moves. Each group shows thumbnails, metadata
(resolution, size, EXIF, category), and the recommended keep/move action.

Usage:
    python3 scripts/generate_preview.py \
        --duplicates duplicates.csv \
        --index photo_index.db \
        --output preview.html
"""

import argparse
import base64
import csv
import html
import os
import sqlite3
import sys
from collections import defaultdict

from constants import format_size, VIDEO_EXTS


def get_thumbnail_base64(path: str, max_size: int = 200) -> str:
    """Generate a base64-encoded thumbnail for an image."""
    try:
        from PIL import Image
        import io

        # Register HEIF opener if available
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass

        with Image.open(path) as img:
            # Convert HEIC/RGBA to RGB
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Create thumbnail
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


MATCH_TYPE_LABELS = {
    "exact_sha256": "Identical SHA-256",
    "exact_phash": "Identical pHash",
    "fuzzy_phash": "Similar pHash",
    "scaled": "Scaled duplicate",
    "cross_format": "Cross-format",
    "burst_subsec": "Burst photo",
    "apple_quality_vector": "Apple QL similar",
    "cnn_mobilenet": "CNN (MobileNet) similar",
}


def generate_preview_html(duplicates_csv: str, index_db: str, move_plan_csv: str = None,
                          max_groups: int = 500) -> str:
    """Generate HTML preview page.

    Args:
        duplicates_csv: Path to duplicates CSV
        index_db: Path to SQLite metadata index
        move_plan_csv: Optional path to move plan CSV
        max_groups: Maximum number of groups to render (prevents huge HTML files)
    """
    # Load metadata
    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row
    metadata = {}
    cursor = conn.execute("SELECT * FROM photos")
    for row in cursor:
        metadata[row["file_path"]] = dict(row)
    conn.close()

    # Load duplicates groups
    groups = defaultdict(list)
    with open(duplicates_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gid = row.get("group_id", "")
            groups[gid].append(row)

    # Load move plan (optional)
    move_actions = {}  # source_path -> action info
    if move_plan_csv and os.path.exists(move_plan_csv):
        with open(move_plan_csv, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                move_actions[row.get("source_path", "")] = row

    # Generate HTML
    html_parts = []
    html_parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SnapTidy — 重复照片预览</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #f5f5f7; color: #1d1d1f; padding: 20px; }
h1 { font-size: 24px; font-weight: 600; margin-bottom: 8px; }
.subtitle { color: #86868b; font-size: 14px; margin-bottom: 24px; }
.group { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px;
         box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.group-header { display: flex; justify-content: space-between; align-items: center;
                margin-bottom: 16px; border-bottom: 1px solid #f0f0f0; padding-bottom: 12px; }
.group-id { font-size: 16px; font-weight: 600; }
.match-type { background: #e8e8ed; color: #48484a; padding: 4px 10px; border-radius: 6px;
              font-size: 12px; font-weight: 500; }
.cards { display: flex; gap: 12px; flex-wrap: wrap; }
.card { border: 2px solid #e8e8ed; border-radius: 10px; padding: 12px; min-width: 200px;
        max-width: 260px; position: relative; }
.card.keep { border-color: #34c759; background: #f0fdf4; }
.card.move { border-color: #ff9500; background: #fff8f0; }
.badge { position: absolute; top: 8px; right: 8px; padding: 2px 8px; border-radius: 4px;
         font-size: 11px; font-weight: 600; text-transform: uppercase; }
.badge.keep { background: #34c759; color: white; }
.badge.move { background: #ff9500; color: white; }
.thumbnail { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px;
             background: #f0f0f0; margin-bottom: 8px; }
.meta { font-size: 12px; color: #86868b; line-height: 1.6; }
.meta strong { color: #1d1d1f; }
.filename { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden;
            text-overflow: ellipsis; margin-bottom: 4px; }
.summary { background: white; border-radius: 12px; padding: 20px; margin-bottom: 24px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.08); display: flex; gap: 32px; flex-wrap: wrap; }
.stat { text-align: center; }
.stat-value { font-size: 28px; font-weight: 700; color: #1d1d1f; }
.stat-label { font-size: 12px; color: #86868b; margin-top: 2px; }
.no-thumb { display: flex; align-items: center; justify-content: center;
            width: 100%; aspect-ratio: 1; background: #f0f0f0; border-radius: 6px;
            color: #86868b; font-size: 12px; margin-bottom: 8px; }

/* Dark mode */
@media (prefers-color-scheme: dark) {
  body { background: #1c1c1e; color: #e5e5e7; }
  h1 { color: #e5e5e7; }
  .subtitle { color: #98989d; }
  .group { background: #2c2c2e; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
  .group-header { border-bottom-color: #38383a; }
  .match-type { background: #3a3a3c; color: #c7c7cc; }
  .card { border-color: #38383a; }
  .card.keep { background: #1a2e1e; }
  .card.move { background: #2e2a1a; }
  .thumbnail { background: #3a3a3c; }
  .no-thumb { background: #3a3a3c; color: #636366; }
  .meta { color: #98989d; }
  .meta strong { color: #e5e5e7; }
  .filename { color: #e5e5e7; }
  .summary { background: #2c2c2e; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
  .stat-value { color: #e5e5e7; }
  .stat-label { color: #98989d; }
}

/* Responsive */
@media (max-width: 768px) {
  body { padding: 12px; }
  h1 { font-size: 18px; }
  .summary { flex-direction: column; gap: 12px; padding: 16px; }
  .stat-value { font-size: 22px; }
  .group { padding: 12px; }
  .cards { flex-direction: column; }
  .card { min-width: 100%; max-width: 100%; }
}
</style>
</head>
<body>
<h1>SnapTidy 重复照片预览</h1>
""")

    # Summary stats
    total_images = sum(len(v) for v in groups.values())
    total_groups = len(groups)
    match_type_counts = defaultdict(int)
    for gid, members in groups.items():
        mt = members[0].get("match_type", "unknown")
        match_type_counts[mt] += 1

    html_parts.append(f'<div class="summary">')
    html_parts.append(f'<div class="stat"><div class="stat-value">{total_groups}</div><div class="stat-label">重复组数</div></div>')
    html_parts.append(f'<div class="stat"><div class="stat-value">{total_images}</div><div class="stat-label">涉及图片</div></div>')
    for mt, count in sorted(match_type_counts.items()):
        label = MATCH_TYPE_LABELS.get(mt, mt)
        html_parts.append(f'<div class="stat"><div class="stat-value">{count}</div><div class="stat-label">{label}</div></div>')
    html_parts.append(f'</div>')

    # Groups (limit to max_groups to prevent huge HTML files)
    rendered_groups = 0
    skipped_groups = 0
    for gid, members in sorted(groups.items(), key=lambda x: int(x[0])):
        if rendered_groups >= max_groups:
            skipped_groups = len(groups) - rendered_groups
            break
        rendered_groups += 1
        mt = members[0].get("match_type", "unknown")
        mt_label = MATCH_TYPE_LABELS.get(mt, mt)
        html_parts.append(f'<div class="group">')
        html_parts.append(f'<div class="group-header">')
        html_parts.append(f'<span class="group-id">Group {gid}</span>')
        html_parts.append(f'<span class="match-type">{mt_label}</span>')
        html_parts.append(f'</div>')
        html_parts.append(f'<div class="cards">')

        for member in members:
            path = member.get("file_path", "")
            meta = metadata.get(path, {})
            fname = meta.get("filename", os.path.basename(path))
            fname_escaped = html.escape(fname)
            ext = meta.get("extension", "")
            w = meta.get("width", "")
            h = meta.get("height", "")
            size = meta.get("size_bytes", "0")
            cat = meta.get("category", "")
            folder = meta.get("folder_tag", "")
            has_exif = meta.get("has_exif", 0)
            camera = meta.get("camera_model", "")
            phash = member.get("phash", "")[:16]

            # Determine keep/move status
            action_info = move_actions.get(path, {})
            is_moved = bool(action_info)
            status_class = "move" if is_moved else "keep"
            status_label = "MOVE" if is_moved else "KEEP"

            # Thumbnail
            thumb_b64 = get_thumbnail_base64(path)
            if thumb_b64:
                thumb_html = f'<img class="thumbnail" src="data:image/jpeg;base64,{thumb_b64}" alt="{fname_escaped}">'
            elif ext in VIDEO_EXTS:
                thumb_html = '<div class="no-thumb">视频</div>'
            else:
                thumb_html = '<div class="no-thumb">无预览</div>'

            # Format size
            try:
                size_str = format_size(int(size))
            except (ValueError, TypeError):
                size_str = "?"

            html_parts.append(f'''
<div class="card {status_class}">
  <span class="badge {status_class}">{status_label}</span>
  {thumb_html}
  <div class="filename" title="{fname_escaped}">{fname_escaped}</div>
  <div class="meta">
    <strong>{html.escape(str(w))}×{html.escape(str(h))}</strong> · {html.escape(size_str)}<br>
    类别: <strong>{html.escape(str(cat))}</strong><br>
    文件夹: <strong>{html.escape(str(folder))}</strong><br>
    EXIF: {"有" if has_exif else "无"} · {html.escape(str(camera))}<br>
    <span style="color:#c7c7cc">哈希: {html.escape(phash)}…</span>
  </div>
</div>''')

        html_parts.append(f'</div></div>')

    if skipped_groups > 0:
        html_parts.append(f'''
<div class="group" style="text-align:center; padding:30px; color:#86868b;">
  <p style="font-size:16px;">⚠️ 仅显示前 {max_groups} / {total_groups} 组</p>
  <p style="font-size:13px;">还有 {skipped_groups} 组未显示，以控制页面大小。</p>
  <p style="font-size:13px;">使用 <code>--max-groups {total_groups}</code> 显示全部。</p>
</div>''')

    html_parts.append('</body></html>')

    return "\n".join(html_parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate HTML preview of duplicate groups with thumbnails")
    parser.add_argument("--duplicates", required=True, help="Duplicates CSV from find_similar_photos.py")
    parser.add_argument("--index", "-i", dest="index", required=True, help="SQLite metadata index")
    parser.add_argument("--plan", default="", help="Move plan CSV (optional, shows KEEP/MOVE labels)")
    parser.add_argument("--output", "--report", "-o", dest="output", required=True,
                        help="Output HTML file path (alias: --report)")
    parser.add_argument("--max-groups", type=int, default=500,
                        help="Maximum number of duplicate groups to render (default: 500, prevents huge HTML)")
    args = parser.parse_args()

    html = generate_preview_html(
        os.path.abspath(args.duplicates),
        os.path.abspath(args.index),
        os.path.abspath(args.plan) if args.plan else None,
        max_groups=args.max_groups,
    )

    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Preview generated: {output_path}")
    print(f"  Open in browser: file://{output_path}")


if __name__ == "__main__":
    main()
