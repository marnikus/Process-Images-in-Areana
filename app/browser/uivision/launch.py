"""Finding + starting Firefox — no debugger, no driver, no remote control.

The owner's critical rule, enforced here: the argv is EXACTLY
`[binary, autorun-url]` and nothing else may ever ride along. No `-no-remote`,
no `--start-debugger-server`, no geckodriver / Selenium / Playwright /
Puppeteer. A running Firefox hands the URL to its existing instance and opens
it in a new tab (that handoff is why no flag is needed — and why `-no-remote`
would be wrong: it would start a second, isolated browser). A test pins the
argv and bans the deleted vocabulary from this package.
"""

from __future__ import annotations

import os
import shutil
import subprocess

DEFAULT_BINARIES = {
    "windows": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "linux": "firefox",
    "macos": "/Applications/Firefox.app/Contents/MacOS/firefox",
}

# Words that must never appear in a launch argv (the deleted debugger approach).
BANNED_ARG_MARKERS = ("start-debugger-server", "remote-debugging-port", "no-remote",
                      "geckodriver", "selenium", "playwright", "puppeteer", "marionette")


def resolve_binary(configured: str = "", os_name: str = "") -> str:
    """The configured Firefox binary, else this OS's default install path/name."""
    text = (configured or "").strip().strip('"')
    if text:
        return text
    from app.browser.browsers import current_os
    return DEFAULT_BINARIES.get(os_name or current_os(), DEFAULT_BINARIES["linux"])


def binary_exists(binary: str) -> bool:
    """A path is checked on disk; a bare name is trusted to PATH (`which`)."""
    if os.path.isabs(binary) or os.path.sep in binary or (os.name == "nt" and "/" in binary):
        return os.path.exists(binary)
    return shutil.which(binary) is not None


def build_argv(binary: str, url: str) -> list:
    """`[binary, url]` — the whole launch line (the critical rule as code)."""
    argv = [binary, url]
    bad = [marker for arg in argv for marker in BANNED_ARG_MARKERS if marker in str(arg).lower()]
    if bad:
        raise ValueError(f"launch refuses debugger/driver vocabulary: {', '.join(sorted(set(bad)))}")
    return argv


def launch(argv, popen=None):
    """Start Firefox with the autorun URL; returns the process handle (Popen seam)."""
    factory = popen or subprocess.Popen
    return factory(argv)
