"""Arena download — JS + Python fallback (C3).

RULE18: file 150-300, func ≤20, CC≤10.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Tuple

from ..page_recovery import evaluate_failure  # B8: why the page answered nothing
from .js_snippets import JS_DOWNLOAD_IMAGE

log = logging.getLogger("arena")


def _sync_fetch(url: str):
    import urllib.request
    import ssl
    hdr = {"User-Agent": "Mozilla/5.0 Chrome/120", "Accept": "image/*,*/*;q=0.8"}
    req = urllib.request.Request(url, headers=hdr)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=45, context=ctx) as r:
            return r.read(), r.headers.get("Content-Type", "") or "", 200
    except Exception:
        with urllib.request.urlopen(req, timeout=45) as r2:
            ctype = getattr(r2.headers, "get", lambda k, d="": d)("Content-Type", "") or ""
            return r2.read(), ctype, 200


async def _python_download(cdp, src: str, log_cb) -> Tuple[bool, bytes, str]:
    loop = asyncio.get_event_loop()
    try:
        data, ctype, _ = await loop.run_in_executor(None, lambda: _sync_fetch(src))
        if not data or len(data) < 100:
            return False, b"", f"Too small {len(data)}"
        low = data[:200].lower()
        if b"<html" in low or b"<!doctype" in low:
            return False, b"", f"HTML page: {data[:500].decode(errors='ignore')[:200]}"
        log_cb(f"Python download {len(data)} bytes {ctype} {src[:60]}...", "success")
        return True, data, ctype
    except Exception as e:
        return False, b"", f"Python download failed: {e}"


async def _js_download(cdp, src: str) -> Tuple[bool, bytes, str, str]:
    js = f";({JS_DOWNLOAD_IMAGE})({json.dumps(src)})"
    try:
        result = await cdp.evaluate(js)
        if result and result.get("ok"):
            data = bytes(result.get("bytes", []))
            if len(data) > 100 and b"<html" not in data[:100].lower():
                return True, data, result.get("contentType", ""), ""
            return False, b"", "", f"JS returned HTML/small {len(data)}"
        err = result.get("error") if result else f"No result ({evaluate_failure(cdp) or 'empty answer'})"
        return False, b"", "", f"JS download failed {str(err)[:120]}"
    except Exception as e:
        return False, b"", "", f"JS download exc {e}"


async def download_image(cdp, src: str, log_cb) -> Tuple[bool, bytes, str]:
    ok, data, ctype, err = await _js_download(cdp, src)
    if ok:
        return True, data, ctype
    if err:
        log_cb(f"{err} trying Python", "warn")
    ok2, data2, ctype2 = await _python_download(cdp, src, log_cb)
    if ok2:
        return True, data2, ctype2
    log_cb(f"Python download rejected: {ctype2[:120]}", "warn")
    return False, b"", f"All methods failed for {src[:120]}"
