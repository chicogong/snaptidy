#!/usr/bin/env python3
"""Validate SnapTidy's portable skill package without third-party modules."""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"


def read_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    """Return top-level scalar frontmatter fields and Markdown body."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    if not match:
        raise AssertionError(f"Missing YAML frontmatter: {path}")

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if line.startswith((" ", "\t")) or not line.strip():
            continue
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip().strip('"')
    return fields, match.group(2)


def markdown_targets(text: str) -> list[str]:
    """Return local Markdown link targets."""
    return [
        target
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
        if not re.match(r"(?:https?|mailto):", target)
    ]


class SkillContractTests(unittest.TestCase):
    """Cross-agent packaging and safety contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fields, cls.body = read_frontmatter(SKILL)
        cls.text = SKILL.read_text(encoding="utf-8")

    def test_frontmatter_is_portable(self) -> None:
        # Required fields per agentskills.io spec
        self.assertIn("name", self.fields)
        self.assertIn("description", self.fields)
        self.assertEqual(self.fields["name"], "snaptidy")
        # Optional fields allowed: license, compatibility, allowed-tools, metadata
        allowed = {"name", "description", "license", "compatibility", "allowed-tools", "metadata"}
        extra = set(self.fields) - allowed
        self.assertFalse(extra, f"Unexpected frontmatter fields: {extra}")
        description = self.fields["description"]
        self.assertTrue(description.startswith("Use when "))
        self.assertLessEqual(len(description), 500)

    def test_core_is_concise(self) -> None:
        self.assertLessEqual(len(self.text.splitlines()), 180)
        self.assertLessEqual(len(self.text.split()), 1100)

    def test_safety_invariants_are_explicit(self) -> None:
        required = (
            "Never permanently delete files",
            "Never modify `.photoslibrary` or `.photolibrary` packages directly",
            "explicit confirmation",
            "Finder > Put Back",
            "30-day",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.body)
        self.assertIn("Trash operations cannot be undone with `--undo`", self.body)

    def test_local_links_resolve(self) -> None:
        paths = [SKILL, *sorted((ROOT / "references").glob("*.md"))]
        for path in paths:
            for target in markdown_targets(path.read_text(encoding="utf-8")):
                clean_target = target.split("#", 1)[0]
                if clean_target:
                    self.assertTrue(
                        (path.parent / clean_target).exists(),
                        f"Broken link in {path}: {target}",
                    )

    def test_documented_scripts_exist(self) -> None:
        scripts = set(re.findall(r"`([a-z0-9_]+\.py)(?:\s[^`]*)?`", self.body))
        for script in scripts:
            self.assertTrue((ROOT / "scripts" / script).is_file(), script)

    def test_release_versions_match(self) -> None:
        clawhub = (ROOT / "clawhub.yaml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        versions = [
            re.search(r"^version:\s*([0-9.]+)$", clawhub, re.MULTILINE).group(1),
            re.search(r"Version-([0-9.]+)-", readme).group(1),
            re.search(r"Version-([0-9.]+)-", zh_readme).group(1),
        ]
        self.assertEqual(len(set(versions)), 1, versions)

    def test_openai_adapter_matches_skill(self) -> None:
        adapter = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "SnapTidy"', adapter)
        self.assertRegex(adapter, r'short_description: "[^"\n]{25,64}"')
        self.assertIn("$snaptidy", adapter)
        self.assertNotIn("dependencies:", adapter)

    def test_representative_cli_help(self) -> None:
        scripts = (
            "quick_scan.py",
            "organize_photos.py",
            "scan_photos.py",
            "scan_photos_library.py",
            "find_exact_duplicates.py",
            "find_similar_photos.py",
            "apply_move_plan.py",
            "import_to_photos.py",
            "edit_exif.py",
            "library_stats.py",
        )
        for script in scripts:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script), "--help"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
