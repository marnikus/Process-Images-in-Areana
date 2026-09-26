"""Arena download — JS + Python fallback (C3).

RULE18: file 150-300, func ≤20, CC≤10.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Tuple

from ..image_fetch import fetch_bytes     # the one HTTP fetch (Chrome + Firefox lanes)
from ..page_recovery import evaluate_failure  # B8: why the page answered nothing
from .js_snippets import JS_DOWNLOAD_IMAGE

log = logging.getLogger("arena")


async def _python_download(cdp, src: str, log_cb) -> Tuple[bool, bytes, str]:
    """Page-side download failed → fetch the same URL directly (2026-09-25: shared)."""
    loop = asyncio.get_event_loop()
    ok, data, ctype, err = await loop.run_in_executor(None, lambda: fetch_bytes(src))
    if not ok:
        return False, b"", err
    log_cb(f"Python download {len(data)} bytes {ctype} {src[:60]}...", "success")
    return True, data, ctype


def _no_result(cdp) -> str:
    """B8: name why the page answered nothing (transport record, else generic)."""
    return f"No result ({evaluate_failure(cdp) or 'empty answer'})"


async def _js_download(cdp, src: str) -> Tuple[bool, bytes, str, str]:
    js = f";({JS_DOWNLOAD_IMAGE})({json.dumps(src)})"
    try:
        result = await cdp.evaluate(js)
        if result and result.get("ok"):
            data = bytes(result.get("bytes", []))
            if len(data) > 100 and b"<html" not in data[:100].lower():
                return True, data, result.get("contentType", ""), ""
            return False, b"", "", f"JS returned HTML/small {len(data)}"
        err = result.get("error") if result else _no_result(cdp)
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
