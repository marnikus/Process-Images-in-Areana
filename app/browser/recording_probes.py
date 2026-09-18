"""Recording probe builders — page-side JS payloads for CDP evaluation.

Sources live in `recording_js/` next to this file as plain JS so node tests
(tests/js/test_recording_probes.mjs) execute the exact strings the app sends
(RULE 8). Probes are observation-only and self-contained.
"""

from __future__ import annotations

from pathlib import Path

_JS_DIR = Path(__file__).parent / "recording_js"


def _read(name: str) -> str:
    return (_JS_DIR / name).read_text(encoding="utf-8").strip()


def build_observer_js() -> str:
    """Idempotent MutationObserver install (buffered summaries)."""
    return _read("observer.js")


def build_netwrap_js() -> str:
    """Idempotent fetch/XHR wrapper install (buffered request log)."""
    return _read("netwrap.js")


def build_flush_js() -> str:
    """Drain + clear both buffers; returns {mutations, requests}."""
    return _read("flush.js")


def build_snapshot_js() -> str:
    """Full DOM snapshot with recaptcha fields redacted in-page."""
    return _read("snapshot.js")
