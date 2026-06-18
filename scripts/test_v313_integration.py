#!/usr/bin/env python3
"""Integration tests for v3.13 feature propagation to downstream scripts.

Tests that is_animated, orientation, and AVIF support are correctly
integrated into all downstream scripts.
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image


class V313IntegrationTests(unittest.TestCase):
    """Verify v3.13 features propagated to all downstream scripts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.test_dir = tempfile.mkdtemp(prefix="snaptidy_test_")
        cls.db_path, cls.paths = cls._create_test_db(cls.test_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    @staticmethod
    def _create_test_db(test_dir: str) -> tuple[str, dict[str, str]]:
        """Create a test DB with correct schema and test data."""
        db_path = os.path.join(test_dir, "test.db")

        # Create test images
        img1 = Image.new("RGB", (100, 100), color="red")
        img1_path = os.path.join(test_dir, "photo1.jpg")
        img1.save(img1_path, "JPEG")

        img2 = Image.new("RGB", (100, 100), color="red")
        img2_path = os.path.join(test_dir, "photo2.jpg")
        img2.save(img2_path, "JPEG")

        frames = [Image.new("RGB", (50, 50), color=(i * 50, 0, 0)) for i in range(3)]
        gif_path = os.path.join(test_dir, "animated.gif")
        frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                       format="GIF", duration=100, loop=0)

        rotated_img = Image.new("RGB", (80, 120), color="blue")
        rotated_path = os.path.join(test_dir, "rotated.jpg")
        exif = rotated_img.getexif()
        exif[0x0112] = 6
        rotated_img.save(rotated_path, "JPEG", exif=exif.tobytes())

        screenshot_img = Image.new("RGB", (200, 300), color="gray")
        screenshot_path = os.path.join(test_dir, "screenshot.png")
        screenshot_img.save(screenshot_path, "PNG")

        conn = sqlite3.connect(db_path)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS photos (
            file_path TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            exif_datetime TEXT DEFAULT '',
            file_mtime TEXT DEFAULT '',
            width TEXT DEFAULT '',
            height TEXT DEFAULT '',
            phash TEXT DEFAULT '',
            media_type TEXT NOT NULL DEFAULT 'image',
            category TEXT NOT NULL DEFAULT 'photo',
            gps_latitude TEXT DEFAULT '',
            gps_longitude TEXT DEFAULT '',
            camera_make TEXT DEFAULT '',
            camera_model TEXT DEFAULT '',
            has_exif INTEGER DEFAULT 0,
            folder_tag TEXT DEFAULT '',
            scan_root TEXT DEFAULT '',
            scanned_at TEXT DEFAULT '',
            aspect_ratio TEXT DEFAULT '',
            subsec_time TEXT DEFAULT '',
            format_family TEXT DEFAULT '',
            photos_favorite INTEGER DEFAULT 0,
            photos_hidden INTEGER DEFAULT 0,
            photos_screenshot INTEGER DEFAULT 0,
            photos_duplicate_visibility INTEGER DEFAULT 0,
            photos_cloud_state INTEGER DEFAULT 0,
            photos_albums TEXT DEFAULT '',
            photos_shared_albums TEXT DEFAULT '',
            photos_icloud_locally_available INTEGER DEFAULT -1,
            photos_quality_vector TEXT DEFAULT '',
            place_city TEXT DEFAULT '',
            place_region TEXT DEFAULT '',
            place_country TEXT DEFAULT '',
            place_country_code TEXT DEFAULT '',
            is_animated INTEGER DEFAULT 0,
            orientation INTEGER DEFAULT 1,
            is_icloud INTEGER DEFAULT 0,
            icloud_state TEXT DEFAULT ''
        );
        """)

        def fake_sha(n: int) -> str:
            return hashlib.sha256(str(n).encode()).hexdigest()[:16]

        entries = [
            {
                "file_path": img1_path, "filename": "photo1.jpg", "extension": ".jpg",
                "size_bytes": os.path.getsize(img1_path), "sha256": fake_sha(1),
                "exif_datetime": "2024:01:01 10:00:00", "file_mtime": "1700000000",
                "width": "100", "height": "100", "phash": "ff00ff00ff00ff00",
                "media_type": "image", "category": "photo",
                "gps_latitude": "40.0", "gps_longitude": "116.0",
                "camera_make": "Canon", "camera_model": "EOS", "has_exif": 1,
                "folder_tag": "", "scan_root": "", "scanned_at": "",
                "aspect_ratio": "", "subsec_time": "", "format_family": "JPEG",
                "photos_favorite": 0, "photos_hidden": 0, "photos_screenshot": 0,
                "photos_duplicate_visibility": 0, "photos_cloud_state": 0,
                "photos_albums": "", "photos_shared_albums": "",
                "photos_icloud_locally_available": -1, "photos_quality_vector": "",
                "place_city": "Beijing", "place_region": "",
                "place_country": "CN", "place_country_code": "CN",
                "is_animated": 0, "orientation": 1, "is_icloud": 0, "icloud_state": "",
            },
            {
                "file_path": img2_path, "filename": "photo2.jpg", "extension": ".jpg",
                "size_bytes": os.path.getsize(img2_path), "sha256": fake_sha(2),
                "exif_datetime": "2024:01:01 10:00:00", "file_mtime": "1700000000",
                "width": "100", "height": "100", "phash": "ff00ff00ff00ff00",
                "media_type": "image", "category": "photo",
                "gps_latitude": "40.0", "gps_longitude": "116.0",
                "camera_make": "Canon", "camera_model": "EOS", "has_exif": 1,
                "folder_tag": "", "scan_root": "", "scanned_at": "",
                "aspect_ratio": "", "subsec_time": "", "format_family": "JPEG",
                "photos_favorite": 0, "photos_hidden": 0, "photos_screenshot": 0,
                "photos_duplicate_visibility": 0, "photos_cloud_state": 0,
                "photos_albums": "", "photos_shared_albums": "",
                "photos_icloud_locally_available": -1, "photos_quality_vector": "",
                "place_city": "Beijing", "place_region": "",
                "place_country": "CN", "place_country_code": "CN",
                "is_animated": 0, "orientation": 1, "is_icloud": 0, "icloud_state": "",
            },
            {
                "file_path": gif_path, "filename": "animated.gif", "extension": ".gif",
                "size_bytes": os.path.getsize(gif_path), "sha256": fake_sha(3),
                "exif_datetime": "2024:01:01 11:00:00", "file_mtime": "1700000000",
                "width": "50", "height": "50", "phash": "abcdef0123456789",
                "media_type": "image", "category": "photo",
                "gps_latitude": "", "gps_longitude": "",
                "camera_make": "", "camera_model": "", "has_exif": 0,
                "folder_tag": "", "scan_root": "", "scanned_at": "",
                "aspect_ratio": "", "subsec_time": "", "format_family": "GIF",
                "photos_favorite": 0, "photos_hidden": 0, "photos_screenshot": 0,
                "photos_duplicate_visibility": 0, "photos_cloud_state": 0,
                "photos_albums": "", "photos_shared_albums": "",
                "photos_icloud_locally_available": -1, "photos_quality_vector": "",
                "place_city": "", "place_region": "",
                "place_country": "", "place_country_code": "",
                "is_animated": 1, "orientation": 1, "is_icloud": 0, "icloud_state": "",
            },
            {
                "file_path": rotated_path, "filename": "rotated.jpg", "extension": ".jpg",
                "size_bytes": os.path.getsize(rotated_path), "sha256": fake_sha(4),
                "exif_datetime": "2024:01:01 12:00:00", "file_mtime": "1700000000",
                "width": "80", "height": "120", "phash": "0123456789abcdef",
                "media_type": "image", "category": "photo",
                "gps_latitude": "41.0", "gps_longitude": "117.0",
                "camera_make": "Canon", "camera_model": "EOS", "has_exif": 1,
                "folder_tag": "", "scan_root": "", "scanned_at": "",
                "aspect_ratio": "", "subsec_time": "", "format_family": "JPEG",
                "photos_favorite": 0, "photos_hidden": 0, "photos_screenshot": 0,
                "photos_duplicate_visibility": 0, "photos_cloud_state": 0,
                "photos_albums": "", "photos_shared_albums": "",
                "photos_icloud_locally_available": -1, "photos_quality_vector": "",
                "place_city": "Shanghai", "place_region": "",
                "place_country": "CN", "place_country_code": "CN",
                "is_animated": 0, "orientation": 6, "is_icloud": 0, "icloud_state": "",
            },
            {
                "file_path": screenshot_path, "filename": "screenshot.png", "extension": ".png",
                "size_bytes": os.path.getsize(screenshot_path), "sha256": fake_sha(5),
                "exif_datetime": "", "file_mtime": "1700000000",
                "width": "200", "height": "300", "phash": "",
                "media_type": "image", "category": "screenshot",
                "gps_latitude": "", "gps_longitude": "",
                "camera_make": "", "camera_model": "", "has_exif": 0,
                "folder_tag": "", "scan_root": "", "scanned_at": "",
                "aspect_ratio": "", "subsec_time": "", "format_family": "PNG",
                "photos_favorite": 0, "photos_hidden": 0, "photos_screenshot": 1,
                "photos_duplicate_visibility": 0, "photos_cloud_state": 0,
                "photos_albums": "", "photos_shared_albums": "",
                "photos_icloud_locally_available": -1, "photos_quality_vector": "",
                "place_city": "", "place_region": "",
                "place_country": "", "place_country_code": "",
                "is_animated": 0, "orientation": 1, "is_icloud": 0, "icloud_state": "",
            },
        ]

        for entry in entries:
            cols = ", ".join(entry.keys())
            placeholders = ", ".join(["?"] * len(entry))
            conn.execute(f"INSERT INTO photos ({cols}) VALUES ({placeholders})",
                         list(entry.values()))
        conn.commit()
        conn.close()

        return db_path, {
            "img1": img1_path, "img2": img2_path, "gif": gif_path,
            "rotated": rotated_path, "screenshot": screenshot_path,
        }

    def test_find_similar_photos_animated_filter(self) -> None:
        """Animated GIF should be filtered out of pHash matching."""
        import find_similar_photos as fsp
        groups = fsp.group_by_phash_db(self.db_path, threshold=0)
        all_paths = [g["file_path"] for g in groups]
        animated_in_groups = any("animated.gif" in p for p in all_paths)
        static_in_groups = any("photo1.jpg" in p for p in all_paths)
        self.assertFalse(animated_in_groups, "Animated GIF should be filtered out")
        self.assertTrue(static_in_groups, "Static photo1.jpg should be in groups")

    def test_library_stats_animated_rotated_flags(self) -> None:
        """library_stats should report animated=1 and rotated=1."""
        import library_stats as ls
        stats = ls.collect_stats(self.db_path)
        flags = stats.get("flags", {})
        self.assertEqual(flags.get("animated", 0), 1,
                         f"Expected animated=1, got {flags.get('animated')}")
        self.assertEqual(flags.get("rotated", 0), 1,
                         f"Expected rotated=1, got {flags.get('rotated')}")

    def test_compress_photos_skips_animated(self) -> None:
        """compress_photos should skip animated images."""
        import compress_photos as cp
        entry = {
            "extension": ".gif",
            "size_bytes": 600000,
            "is_animated": 1,
            "file_path": self.paths["gif"],
            "width": 50,
            "height": 50,
        }
        should, reason, _ = cp.should_compress(entry, min_size=1000)
        self.assertFalse(should, f"Animated should not compress, got should={should}")
        self.assertIn("animated", reason, f"Expected animated reason, got {reason}")

    def test_convert_format_has_is_animated_image(self) -> None:
        """convert_format should have is_animated_image function."""
        import convert_format as cf
        self.assertTrue(hasattr(cf, "is_animated_image"),
                        "is_animated_image not found in convert_format")

    def test_detect_corrupted_avif_magic_number(self) -> None:
        """detect_corrupted should correctly validate AVIF magic bytes."""
        import detect_corrupted as dc

        avif_path = os.path.join(self.test_dir, "test.avif")
        with open(avif_path, "wb") as f:
            f.write(b"\x00\x00\x00\x1cftypavif")
            f.write(b"\x00" * 100)
        ok, reason, detail = dc._check_magic_number(avif_path)
        self.assertTrue(ok, f"Valid AVIF should pass, got {reason}: {detail}")

        bad_avif = os.path.join(self.test_dir, "bad.avif")
        with open(bad_avif, "wb") as f:
            f.write(b"\x00\x00\x00\x1cftypheic")
            f.write(b"\x00" * 100)
        ok2, reason2, detail2 = dc._check_magic_number(bad_avif)
        self.assertFalse(ok2, f"Invalid AVIF should fail, got ok={ok2}")

    def test_generate_review_html_includes_v313_fields(self) -> None:
        """generate_review HTML should include is_animated and orientation fields."""
        import generate_review as gr
        html_content = gr.generate_review_html(self.db_path)
        self.assertIn('"is_animated"', html_content,
                      "is_animated field not found in HTML")
        self.assertIn('"orientation"', html_content,
                      "orientation field not found in HTML")


if __name__ == "__main__":
    unittest.main(verbosity=2)
