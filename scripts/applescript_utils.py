#!/usr/bin/env python3
"""Shared AppleScript helpers — escaping and osascript invocation.

Previously each script inlined its own backslash/quote escaping (and one
path, apply_move_plan.move_to_trash, escaped nothing — an injection bug).
This module is the single source of truth.
"""

import subprocess

# Apple-signed system binary. Using the absolute path makes macOS reliably
# attribute automation-permission prompts to osascript rather than to the
# (sandboxed) Python interpreter.
OSASCRIPT = "/usr/bin/osascript"


def escape_applescript(text: str) -> str:
    """Escape a string for safe interpolation into an AppleScript literal.

    Backslashes MUST be escaped before quotes, otherwise the quote escapes
    get double-processed.  Without this, paths/album names containing quotes
    or backslashes break the script or allow AppleScript injection.
    """
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def run_applescript(script: str, timeout: int = 60):
    """Run an AppleScript via osascript.  Returns the CompletedProcess.

    Captures stdout/stderr as text.  Raises subprocess.TimeoutExpired on
    timeout; callers should handle that if they care.
    """
    return subprocess.run(
        [OSASCRIPT, "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
