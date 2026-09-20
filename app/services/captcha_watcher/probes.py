"""Watcher probes — the two page-side JS payloads the Watcher evaluates.

* detect.js  → `{visible, kind, sitekey, invisible, url, …}` (IIFE)
* inject.js  → `(token, sitekey) => {ok, scope, fields, cbCalled, …}`

Both sources live in `app/browser/captcha_js/` (verified against real
arena.ai states on 2026-09-18: the always-present `.grecaptcha-badge`
anchor iframe + hidden `g-recaptcha-response` textarea are NOT a challenge)
and are executed verbatim by tests/js/test_captcha.mjs. The builders in
`app.browser.captcha_probes` own the wrapping, so this module stays the
single service-side entry point without duplicating the file handling.
"""

from __future__ import annotations

from typing import Any, Dict

from app.browser.captcha_probes import build_detect_js, build_inject_js


def detect_js() -> str:
    """Expression returning the detection payload (never throws page-side)."""
    return build_detect_js()


def inject_js(token: str, sitekey: str = "") -> str:
    """Expression applying inject.js to (token, sitekey); returns {ok, …}."""
    return build_inject_js(token, sitekey)


def inject_ok(res: Any) -> bool:
    """True when the page accepted the token (fields set); tolerant parser."""
    return isinstance(res, dict) and bool(res.get("ok"))


def inject_summary(res: Any) -> Dict[str, Any]:
    """Log-safe summary of an inject result (no token material)."""
    if not isinstance(res, dict):
        return {"ok": False, "error": "no result"}
    return {
        "ok": bool(res.get("ok")),
        "scope": str(res.get("scope") or ""),
        "fields": int(res.get("fields") or 0),
        "cb": str(res.get("cbSource") or "none"),
        "cb_called": bool(res.get("cbCalled")),
        "error": str(res.get("error") or res.get("cbError") or ""),
    }
