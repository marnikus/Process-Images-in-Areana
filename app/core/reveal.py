"""Reveal — show a queue file selected in the OS file manager.

Used by the queue 📁 button ("open in explorer"). A hyperlink would open
in-browser; this launches the native file manager with the file selected.
"""
from __future__ import annotations

import os
import subprocess
import sys


def build_reveal_command(path_str: str, platform: str = sys.platform) -> list:
    """argv that reveals path_str in the platform file manager (pure)."""
    if platform == "win32":
        return ["explorer", "/select,", os.path.normpath(path_str)]
    if platform == "darwin":
        return ["open", "-R", path_str]
    return ["xdg-open", os.path.dirname(path_str) or "."]


def reveal_in_file_manager(path_str: str) -> tuple:
    """Reveal an existing file; returns (ok, error_message). Non-blocking."""
    if not path_str or not os.path.isfile(path_str):
        return False, f"file not found: {path_str}"
    try:
        subprocess.Popen(build_reveal_command(path_str))  # noqa: S603
    except Exception as e:
        return False, str(e)
    return True, ""
