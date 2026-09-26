"""Fetch a generated image over HTTP and gate the response (shared by both lanes).

The correlated result `src` is a presigned https URL that downloads without
cookies (Firefox image job design D-8 / S5), so both browser lanes pull the
bytes from Python and never through the browser's DevTools socket
(docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md D-1).

* `check_response` rejects HTTP ≠ 200, an HTML page, a body under
  `MIN_BYTES` and a body shorter than its Content-Length (partial);
* `fetch_image` = GET + gate → `(bytes, content_type)` or `OutputError`.

Imports: stdlib only (utils layer).
"""

from __future__ import annotations

import urllib.request
from typing import Tuple

MIN_BYTES = 100
_UA = {"User-Agent": "Mozilla/5.0 (Arena Image Processor)", "Accept": "image/*,*/*;q=0.8"}


class OutputError(Exception):
    """A result that must not be saved (named reason)."""


def check_response(status: int, ctype: str, length, data: bytes) -> None:
    """The download gate (raises OutputError with the reason)."""
    if status != 200:
        raise OutputError(f"HTTP {status}")
    head = data[:64].lstrip().lower()
    if "text/html" in (ctype or "").lower() or head.startswith((b"<!doctype", b"<html")):
        raise OutputError("got an HTML page, not an image")
    if len(data) < MIN_BYTES:
        raise OutputError(f"only {len(data)} bytes")
    if length not in (None, "") and str(length).isdigit() and int(length) != len(data):
        raise OutputError(f"partial download {len(data)}/{length} bytes")


def fetch_image(src: str, timeout: float, opener=None) -> Tuple[bytes, str]:
    """GET the result; the checked `(bytes, content_type)` or OutputError."""
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(urllib.request.Request(src, headers=_UA), timeout=timeout) as resp:
            data = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
            headers = getattr(resp, "headers", {}) or {}
            ctype = headers.get("Content-Type", "") or ""
            check_response(status, ctype, headers.get("Content-Length"), data)
            return data, ctype
    except OutputError:
        raise
    except Exception as exc:
        raise OutputError(f"download failed: {exc}") from exc
