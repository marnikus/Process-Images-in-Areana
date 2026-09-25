"""One result URL → bytes, over plain HTTPS — no page, no CDP.

Extracted from the Chrome download fallback (2026-09-25, design
`archive/2026-09-25-firefox-image-job-pipeline`) so both browsers deliver a
correlated result through the SAME code: Chrome tries the page first and lands
here when the page cannot (CORS/context loss), Firefox has no page-side
evaluator on its lane and calls this directly.

The contract is the caller's honesty switch (RULE 4): a rejected body names
*why* ("Too small 12", "HTML page: …", "Python download failed: …"), so the
caller can tell "the download never started" from "a login page arrived".

Imports: stdlib only.
"""

from __future__ import annotations

import ssl
import urllib.request

MIN_BYTES = 100
TIMEOUT_SEC = 45
HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120", "Accept": "image/*,*/*;q=0.8"}


def _read(response) -> tuple:
    """(body, content-type) of one urllib response."""
    headers = getattr(response, "headers", None)
    ctype = headers.get("Content-Type", "") if headers is not None else ""
    return response.read(), ctype or ""


def _fetch_once(req, timeout: int, context):
    """One urlopen: with the SSL context when one was built, without it otherwise."""
    if context is None:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return _read(response)
    with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
        return _read(response)


def _inspect(data: bytes, ctype: str) -> tuple:
    """(ok, data, ctype, error) — the size and HTML gates every caller shares."""
    if not data or len(data) < MIN_BYTES:
        return False, b"", ctype, f"Too small {len(data)}"
    low = data[:200].lower()
    if b"<html" in low or b"<!doctype" in low:
        return False, b"", ctype, f"HTML page: {data[:200].decode(errors='ignore')[:120]}"
    return True, data, ctype, ""


def fetch_bytes(url: str, timeout: int = TIMEOUT_SEC) -> tuple:
    """(ok, data, ctype, error) for one URL; never raises.

    The verified-context attempt runs first; a TLS failure retries with the
    interpreter default, exactly like the Chrome fallback it replaces.
    """
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        data, ctype = _fetch_once(req, timeout, ssl.create_default_context())
    except Exception:
        try:
            data, ctype = _fetch_once(req, timeout, None)
        except Exception as exc:
            return False, b"", "", f"Python download failed: {exc}"
    return _inspect(data, ctype)
