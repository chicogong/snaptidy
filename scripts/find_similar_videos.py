#!/usr/bin/env python3
"""Find similar/duplicate videos using frame sampling + perceptual hash.

Unlike image dedup which uses a single pHash, video dedup samples frames
at regular intervals and computes perceptual hashes for each frame. Two
videos are considered similar if enough sampled frames match.

Detection method:
  1. Extract N frames evenly spaced throughout the video (using ffmpeg)
  2. Compute pHash for each frame
  3. Compare frame hashes between video pairs
  4. Two videos match if >= threshold% of frames are similar

Requires: ffmpeg (system binary) + Pillow + imagehash

Usage:
    # Find similar videos in index
    python3 scripts/find_similar_videos.py --index photo_index.db --output similar_videos.csv

    # Custom frame count and threshold
    python3 scripts/find_similar_videos.py --index photo_index.db --output similar_videos.csv \
        --frames 8 --threshold 0.6

    # Quick scan with fewer frames
    python3 scripts/find_similar_videos.py --index photo_index.db --output similar_videos.csv \
        --frames 3 --threshold 0.7
"""

import argparse
import csv
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict

from constants import VIDEO_EXTS, format_size

try:
    from PIL import Image
    import imagehash
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available on PATH."""
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def extract_frames(video_path: str, num_frames: int = 5,
                   tmp_dir: str = None) -> list:
    """Extract evenly-spaced frames from a video using ffmpeg.

    Returns list of file paths to extracted JPEG frames.
    """
    if not check_ffmpeg():
        return []

    # Get video duration
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30
        )
        duration = float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        # Fallback: try to get duration from file
        return []

    if duration <= 0:
        return []

    # Calculate frame timestamps
    timestamps = []
    if num_frames == 1:
        timestamps = [duration / 2]
    else:
        interval = duration / (num_frames + 1)
        timestamps = [interval * (i + 1) for i in range(num_frames)]

    # Extract frames
    frame_paths = []
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp(prefix="snaptidy_video_")

    for i, ts in enumerate(timestamps):
        out_path = os.path.join(tmp_dir, f"frame_{i:03d}.jpg")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-ss", str(ts), "-i", video_path,
                 "-vframes", "1", "-q:v", "2", "-vf", "scale=320:-2",
                 out_path],
                capture_output=True, timeout=30
            )
            if result.returncode == 0 and os.path.exists(out_path):
                frame_paths.append(out_path)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    return frame_paths


def compute_video_phashes(video_path: str, num_frames: int = 5) -> list:
    """Compute perceptual hashes for sampled frames of a video.

    Returns list of pHash strings.
    """
    if not PILLOW_AVAILABLE or not IMAGEHASH_AVAILABLE:
        return []

    tmp_dir = tempfile.mkdtemp(prefix="snaptidy_video_")
    try:
        frame_paths = extract_frames(video_path, num_frames, tmp_dir)
        hashes = []

        for fp in frame_paths:
            try:
                with Image.open(fp) as img:
                    h = str(imagehash.average_hash(img.convert("RGB")))
                    hashes.append(h)
            except Exception:
                continue

        return hashes
    finally:
        # Cleanup temp frames
        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def compare_video_hashes(hashes_a: list, hashes_b: list,
                         hamming_threshold: int = 10) -> float:
    """Compare two sets of video frame hashes.

    Returns similarity ratio (0.0-1.0) — fraction of frames that match.
    """
    if not hashes_a or not hashes_b:
        return 0.0

    matches = 0
    total = min(len(hashes_a), len(hashes_b))

    for ha, hb in zip(hashes_a, hashes_b):
        try:
            ph_a = imagehash.hex_to_hash(ha)
            ph_b = imagehash.hex_to_hash(hb)
            if ph_a - ph_b <= hamming_threshold:
                matches += 1
        except Exception:
            continue

    return matches / total if total > 0 else 0.0


def find_similar_videos(index_path: str, num_frames: int = 5,
                        threshold: float = 0.6,
                        hamming: int = 10) -> list:
    """Find similar videos in the index.

    Returns list of {group_id, file_a, file_b, similarity, match_type}
    """
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row

    # Get all videos
    cursor = conn.execute(
        "SELECT file_path, filename, extension, size_bytes, sha256 "
        "FROM photos WHERE media_type = 'video'"
    )
    videos = [dict(row) for row in cursor]
    conn.close()

    if len(videos) < 2:
        print("  Fewer than 2 videos found — nothing to compare.")
        return []

    print(f"  Computing frame hashes for {len(videos)} videos...")

    # Compute hashes for each video
    video_hashes = {}
    for idx, v in enumerate(videos):
        if idx % 10 == 0:
            print(f"    Processing video {idx}/{len(videos)}...")
        if not os.path.exists(v["file_path"]):
            continue
        hashes = compute_video_phashes(v["file_path"], num_frames)
        if hashes:
            video_hashes[v["file_path"]] = {
                "hashes": hashes,
                "filename": v["filename"],
                "size_bytes": v["size_bytes"],
                "sha256": v["sha256"],
            }

    print(f"  Computed hashes for {len(video_hashes)} videos")

    # Compare all pairs
    paths = list(video_hashes.keys())
    groups = []
    group_id = 0

    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            a = video_hashes[paths[i]]
            b = video_hashes[paths[j]]

            # Skip exact duplicates (same SHA-256)
            if a["sha256"] and b["sha256"] and a["sha256"] == b["sha256"]:
                group_id += 1
                groups.append({
                    "group_id": f"v{group_id}",
                    "file_a": paths[i],
                    "file_b": paths[j],
                    "name_a": a["filename"],
                    "name_b": b["filename"],
                    "size_a": a["size_bytes"],
                    "size_b": b["size_bytes"],
                    "similarity": 1.0,
                    "match_type": "exact_sha256",
                })
                continue

            similarity = compare_video_hashes(a["hashes"], b["hashes"], hamming)
            if similarity >= threshold:
                group_id += 1
                groups.append({
                    "group_id": f"v{group_id}",
                    "file_a": paths[i],
                    "file_b": paths[j],
                    "name_a": a["filename"],
                    "name_b": b["filename"],
                    "size_a": a["size_bytes"],
                    "size_b": b["size_bytes"],
                    "similarity": round(similarity, 3),
                    "match_type": "video_phash",
                })

    return groups


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find similar/duplicate videos using frame sampling + perceptual hash")
    parser.add_argument("--index", "-i", dest="index", required=True,
                        help="Path to SQLite metadata index")
    parser.add_argument("--output", "-o", dest="output", required=True,
                        help="Output CSV path for similar video pairs")
    parser.add_argument("--frames", type=int, default=5,
                        help="Number of frames to sample per video (default: 5)")
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="Minimum similarity ratio to report (default: 0.6)")
    parser.add_argument("--hamming", type=int, default=10,
                        help="Max Hamming distance for matching frames (default: 10)")
    args = parser.parse_args()

    if not os.path.exists(args.index):
        print(f"Error: Index not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    if not check_ffmpeg():
        print("Error: ffmpeg is required for video dedup.", file=sys.stderr)
        print("       Install with: brew install ffmpeg", file=sys.stderr)
        sys.exit(1)

    if not PILLOW_AVAILABLE or not IMAGEHASH_AVAILABLE:
        print("Error: Pillow and imagehash are required.", file=sys.stderr)
        print("       Install with: pip install Pillow imagehash", file=sys.stderr)
        sys.exit(1)

    print("🎬 Finding similar videos...")
    results = find_similar_videos(
        os.path.abspath(args.index),
        num_frames=args.frames,
        threshold=args.threshold,
        hamming=args.hamming,
    )

    # Write output
    output_path = os.path.abspath(args.output)
    if results:
        fieldnames = ["group_id", "file_a", "file_b", "name_a", "name_b",
                      "size_a", "size_b", "similarity", "match_type"]
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    print(f"\n{'=' * 50}")
    print(f"Video Dedup Report")
    print(f"  Similar pairs:   {len(results)}")
    if results:
        total_size = sum(max(r["size_a"], r["size_b"]) for r in results if r["match_type"] != "exact_sha256")
        print(f"  Potential savings: {format_size(total_size)}")
    print(f"  Report saved:   {output_path}")


if __name__ == "__main__":
    main()
