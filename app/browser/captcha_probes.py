"""Captcha probe builders — page-side JS payloads for CDP evaluation.

The probe sources live in `captcha_js/` next to this file as plain JS so
node tests (tests/js/test_captcha.mjs) execute the exact strings the app
sends to the target page (RULE 8). The target page is external, so each
probe must stay self-contained (no imports, no script tags).
"""

from __future__ import annotations

import json
from pathlib import Path

_JS_DIR = Path(__file__).parent / "captcha_js"


def _read(name: str) -> str:
    return (_JS_DIR / name).read_text(encoding="utf-8").strip()


def build_detect_js() -> str:
    """Visibility + kind + sitekey probe (IIFE, returns a JSON-able dict)."""
    return _read("detect.js")


def build_visible_js() -> str:
    """Gate predicate for is_security_dialog_visible (boolean IIFE).

    Badge-aware: the always-present .grecaptcha-badge widget is on screen
    in the normal state and must never count as a visible captcha.
    """
    return ";" + _read("visible.js")


def build_inject_js(token: str) -> str:
    """Token-injection probe: wraps the (token)=>… function with the payload."""
    return f"({_read('inject.js')})({json.dumps(token)})"


def build_continue_js() -> str:
    """Dialog action-button click probe (best effort, IIFE)."""
    return _read("continue_click.js")
