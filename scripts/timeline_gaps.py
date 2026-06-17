#!/usr/bin/env python3
"""Detect abnormal gaps in photo timeline — missing periods.

Analyzes the date distribution of photos in the index DB and identifies
time gaps that likely indicate missing photos (lost, deleted, or not
imported). Uses adaptive thresholding based on the user's shooting
frequency patterns.

Gap detection:
  - Daily gaps: no photos for N days when the user typically shoots daily
  - Weekly gaps: no photos for N weeks when the user typically shoots weekly
  - Seasonal gaps: entire months with zero photos during active periods

Output:
  - List of gap periods with estimated missing photo counts
  - Timeline density heatmap (photos per day/week/month)
  - Suggestions for import sources (camera, phone, cloud)

Usage:
    # Detect timeline gaps with default settings
    python timeline_gaps.py --index photo_index.db

    # Custom gap threshold (minimum days to consider as a gap)
    python timeline_gaps.py --index photo_index.db --min-gap-days 14

    # Export report
    python timeline_gaps.py --index photo_index.db --report gaps.csv

    # Include date-inferred photos (from fix_dates.py)
    python timeline_gaps.py --index photo_index.db --include-inferred
"""

import argparse
import csv
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from constants import format_size


# ---------------------------------------------------------------------------
# Timeline analysis
# ---------------------------------------------------------------------------

def load_timeline(index_path: str, include_inferred: bool = False) -> list:
    """Load sorted list of photo dates from index DB.

    Returns list of (date, file_path, date_source) tuples sorted by date.
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Check if date_source column exists (from fix_dates.py)
    available_cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
    has_date_source = "date_source" in available_cols

    query = """
        SELECT file_path, exif_datetime, file_mtime
        FROM photos
        WHERE exif_datetime != '' AND exif_datetime IS NOT NULL
    """
    if not include_inferred and has_date_source:
        query += " AND (date_source IS NULL OR date_source NOT IN ('neighbor', 'file_mtime'))"

    rows = conn.execute(query).fetchall()
    conn.close()

    timeline = []
    for row in rows:
        dt_str = row["exif_datetime"]
        try:
            # Try parsing various date formats
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y:%m:%d %H:%M:%S",
                        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(dt_str[:19] if len(dt_str) >= 19 else dt_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                continue
            timeline.append((dt.date(), row["file_path"]))
        except (ValueError, TypeError):
            continue

    timeline.sort(key=lambda x: x[0])
    return timeline


def compute_shooting_frequency(timeline: list) -> dict:
    """Compute shooting frequency statistics.

    Returns dict with per-day, per-week, per-month stats.
    """
    if not timeline:
        return {"photos_per_day": 0, "photos_per_week": 0, "photos_per_month": 0,
                "active_days": 0, "total_days": 0, "coverage": 0.0}

    dates = [d for d, _ in timeline]
    first_date = dates[0]
    last_date = dates[-1]
    total_days = (last_date - first_date).days + 1

    # Count photos per day
    daily_counts = defaultdict(int)
    for d, _ in timeline:
        daily_counts[d] += 1

    active_days = len(daily_counts)
    total_photos = len(timeline)

    # Monthly counts
    monthly_counts = defaultdict(int)
    for d, _ in timeline:
        month_key = d.strftime("%Y-%m")
        monthly_counts[month_key] += 1

    return {
        "first_date": first_date,
        "last_date": last_date,
        "total_days": total_days,
        "total_photos": total_photos,
        "active_days": active_days,
        "photos_per_day": total_photos / max(total_days, 1),
        "photos_per_active_day": total_photos / max(active_days, 1),
        "photos_per_week": total_photos / max(total_days / 7, 1),
        "photos_per_month": total_photos / max(len(monthly_counts), 1),
        "coverage": active_days / max(total_days, 1) * 100,
        "daily_counts": daily_counts,
        "monthly_counts": monthly_counts,
    }


def detect_gaps(timeline: list, min_gap_days: int = 7,
                adaptive: bool = True) -> list:
    """Detect time gaps in the photo timeline.

    Returns list of gap dicts: {start, end, days, estimated_missing, severity}
    """
    if len(timeline) < 2:
        return []

    dates = sorted(set(d for d, _ in timeline))

    # Compute adaptive threshold if enabled
    if adaptive:
        # Look at intervals between consecutive active days
        intervals = []
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i - 1]).days
            intervals.append(gap)

        if intervals:
            # Use median + 3*IQR as adaptive threshold (robust to outliers)
            sorted_intervals = sorted(intervals)
            n = len(sorted_intervals)
            median = sorted_intervals[n // 2]
            q1 = sorted_intervals[n // 4]
            q3 = sorted_intervals[3 * n // 4]
            iqr = q3 - q1
            adaptive_threshold = max(median + 3 * iqr, min_gap_days)
        else:
            adaptive_threshold = min_gap_days
    else:
        adaptive_threshold = min_gap_days

    # Compute average photos per active day for estimation
    active_day_counts = defaultdict(int)
    for d, _ in timeline:
        active_day_counts[d] += 1
    avg_per_day = sum(active_day_counts.values()) / max(len(active_day_counts), 1)

    # Find gaps
    gaps = []
    for i in range(1, len(dates)):
        gap_days = (dates[i] - dates[i - 1]).days
        if gap_days >= adaptive_threshold:
            # Classify severity
            if gap_days >= 90:
                severity = "critical"
            elif gap_days >= 30:
                severity = "major"
            elif gap_days >= 14:
                severity = "moderate"
            else:
                severity = "minor"

            # Estimate missing photos (exclude the boundary days)
            missing_days = gap_days - 1
            estimated_missing = int(missing_days * avg_per_day * 0.3)
            # Reduce estimate for longer gaps (less likely to shoot every day)
            if missing_days > 30:
                estimated_missing = int(estimated_missing * 0.5)

            gaps.append({
                "start": dates[i - 1],
                "end": dates[i],
                "days": gap_days,
                "missing_days": missing_days,
                "estimated_missing": max(estimated_missing, 1),
                "severity": severity,
            })

    # Sort by gap length (largest first)
    gaps.sort(key=lambda x: x["days"], reverse=True)
    return gaps


def generate_monthly_heatmap(timeline: list) -> dict:
    """Generate monthly photo count heatmap data.

    Returns: {year_month: count}
    """
    monthly = defaultdict(int)
    for d, _ in timeline:
        key = d.strftime("%Y-%m")
        monthly[key] += 1
    return dict(sorted(monthly.items()))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(gaps: list, heatmap: dict, report_path: str):
    """Write gap analysis report to CSV."""
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["type", "start_date", "end_date", "days",
                         "missing_days", "estimated_missing", "severity", "count"])

        for g in gaps:
            writer.writerow([
                "gap", g["start"], g["end"], g["days"],
                g["missing_days"], g["estimated_missing"], g["severity"], ""
            ])

        for month, count in heatmap.items():
            writer.writerow(["monthly", month, "", "", "", "", "", count])


def print_summary(freq: dict, gaps: list, heatmap: dict):
    """Print timeline analysis summary."""
    print(f"\n{'=' * 60}")
    print(f"Timeline Gap Analysis")
    print(f"{'=' * 60}")

    # Overall stats
    print(f"\n📅 Timeline: {freq['first_date']} → {freq['last_date']}")
    print(f"  Total: {freq['total_photos']} photos over {freq['total_days']} days")
    print(f"  Active days: {freq['active_days']} ({freq['coverage']:.1f}% coverage)")
    print(f"  Average: {freq['photos_per_active_day']:.1f} photos/active day")

    # Gap summary
    if not gaps:
        print(f"\n✅ No significant timeline gaps detected!")
        return

    print(f"\n⚠️  Found {len(gaps)} timeline gap(s):")

    # Group by severity
    by_severity = defaultdict(list)
    for g in gaps:
        by_severity[g["severity"]].append(g)

    severity_icons = {"critical": "🔴", "major": "🟠", "moderate": "🟡", "minor": "🟢"}
    for severity in ["critical", "major", "moderate", "minor"]:
        group = by_severity.get(severity, [])
        if group:
            icon = severity_icons[severity]
            print(f"\n  {icon} {severity.upper()} ({len(group)} gap(s)):")
            for g in group[:10]:
                print(f"    {g['start']} → {g['end']}  ({g['days']} days, "
                      f"~{g['estimated_missing']} photos missing)")
            if len(group) > 10:
                print(f"    ... and {len(group) - 10} more")

    # Total estimated missing
    total_missing = sum(g["estimated_missing"] for g in gaps)
    total_gap_days = sum(g["missing_days"] for g in gaps)
    print(f"\n  📊 Total: {total_gap_days} gap-days, ~{total_missing} photos potentially missing")

    # Monthly heatmap (top 12 months by count, or sparse months)
    sparse_months = [(m, c) for m, c in heatmap.items() if c == 0]
    if sparse_months:
        print(f"\n  📭 Months with zero photos ({len(sparse_months)}):")
        for month, _ in sorted(sparse_months)[:12]:
            print(f"    {month}")
        if len(sparse_months) > 12:
            print(f"    ... and {len(sparse_months) - 12} more")

    # Top months by activity
    top_months = sorted(heatmap.items(), key=lambda x: x[1], reverse=True)[:5]
    if top_months:
        print(f"\n  📸 Most active months:")
        for month, count in top_months:
            bar = "█" * min(count // 5, 40)
            print(f"    {month}: {count} photos {bar}")

    # Suggestions
    print(f"\n  💡 Suggestions:")
    if total_missing > 0:
        print(f"     - Check camera SD cards and phone imports for missing photos")
        print(f"     - Look for photos dated during gap periods in cloud storage")
        print(f"     - Run scan with --source on additional directories")
    if by_severity.get("critical"):
        print(f"     - Critical gaps may indicate data loss — investigate immediately")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detect abnormal gaps in photo timeline — find missing periods")
    parser.add_argument("--index", "-i", required=True,
                        help="Path to SQLite metadata index (from scan_photos.py)")
    parser.add_argument("--min-gap-days", type=int, default=7,
                        help="Minimum gap in days to consider as abnormal (default: 7)")
    parser.add_argument("--no-adaptive", action="store_true",
                        help="Disable adaptive gap threshold (use fixed min-gap-days)")
    parser.add_argument("--include-inferred", action="store_true",
                        help="Include photos with inferred dates (from fix_dates.py)")
    parser.add_argument("--report", "-r", default="",
                        help="Write gap analysis report to CSV")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    print("📅 Analyzing photo timeline...")
    start_time = __import__("time").time()

    # Load timeline
    timeline = load_timeline(args.index, include_inferred=args.include_inferred)

    if not timeline:
        print("No dated photos found in index. Run scan_photos.py first.")
        return

    print(f"  Loaded {len(timeline)} dated photos")

    # Compute frequency stats
    freq = compute_shooting_frequency(timeline)

    # Detect gaps
    gaps = detect_gaps(timeline, min_gap_days=args.min_gap_days,
                       adaptive=not args.no_adaptive)

    # Generate heatmap
    heatmap = generate_monthly_heatmap(timeline)

    elapsed = __import__("time").time() - start_time

    # Print summary
    print_summary(freq, gaps, heatmap)
    print(f"\n  Analysis completed in {elapsed:.1f}s")

    # Write report
    if args.report:
        write_report(gaps, heatmap, os.path.abspath(args.report))
        print(f"  Report: {args.report}")


if __name__ == "__main__":
    main()
