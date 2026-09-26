"""Arena download — the result bytes WITHOUT one giant DevTools reply (C3, 2026-09-26).

Order (docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md D-1):

1. `data:` src  → decoded here (no network, no socket);
2. `http(s)` src → Python fetch (`utils.http_image.fetch_image`, the shared
   gate) in an executor — no CDP traffic at all;
3. fallback (blob: src, or Python refused) → the page fetches ONCE into a
   window slot and Python pulls ≤ `CHUNK_CHARS` base64 slices, then frees the
   slot. Before it the link is healed (`page_recovery.heal_link`).

Why: the old path returned the whole image as a JSON number array in one
`Runtime.evaluate` reply; a 20 MB PNG closed the socket with 1009 "message too
big" and nothing reconnected — the job could not save, the next jobs failed.

RULE18: file 150-300, func ≤20, CC≤10.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import uuid
from typing import Callable, Tuple

from ...utils.http_image import OutputError, check_response, fetch_image
from ..page_recovery import LinkLost, evaluate_failure, heal_link
from .js_snippets import JS_FETCH_TO_SLOT, JS_FREE_SLOT, JS_READ_SLOT

log = logging.getLogger("arena")

CHUNK_CHARS = 1_000_000      # base64 chars per reply (≈ 750 KB of image), multiple of 4
PY_TIMEOUT_S = 45.0
Result = Tuple[bool, bytes, str]


def _no_result(cdp) -> str:
    """B8: name why the page answered nothing (transport record, else generic)."""
    return f"No result ({evaluate_failure(cdp) or 'empty answer'})"


def _as_dict(raw) -> dict:
    """An evaluate answer as a dict (real client: dict; fakes: JSON text)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _decode_data_url(src: str) -> Result:
    """`data:image/png;base64,...` → bytes through the same gate as a download."""
    head, _, body = src.partition(",")
    ctype = head[5:].split(";")[0]
    try:
        data = base64.b64decode(body) if ";base64" in head else body.encode("latin-1")
        check_response(200, ctype, None, data)
    except (OutputError, binascii.Error, ValueError) as exc:
        return False, b"", f"data URL rejected: {exc}"
    return True, data, ctype


async def _python_download(src: str, log_cb: Callable) -> Result:
    """GET + gate off the event loop; (ok, bytes, ctype | reason)."""
    loop = asyncio.get_running_loop()
    try:
        data, ctype = await loop.run_in_executor(None, lambda: fetch_image(src, PY_TIMEOUT_S))
    except OutputError as exc:
        return False, b"", f"Python download failed: {exc}"
    log_cb(f"Python download {len(data)} bytes {ctype} {src[:60]}...", "success")
    return True, data, ctype


async def _pull_slices(cdp, key: str, total: int) -> str:
    """Read the slot in `CHUNK_CHARS` slices; raises OutputError on a gap."""
    parts = []
    for start in range(0, total, CHUNK_CHARS):
        part = await cdp.evaluate(f";({JS_READ_SLOT})({json.dumps(key)}, {start}, {CHUNK_CHARS})")
        if not isinstance(part, str) or not part:
            raise OutputError(f"slice at {start}/{total} lost — {_no_result(cdp)}")
        parts.append(part)
    return "".join(parts)


async def _read_slot(cdp, key: str, meta: dict) -> bytes:
    """Slices → bytes; the slot is freed whatever happens."""
    try:
        text = await _pull_slices(cdp, key, int(meta.get("b64len") or 0))
    finally:
        await cdp.evaluate(f";({JS_FREE_SLOT})({json.dumps(key)})")
    data = base64.b64decode(text)
    if len(data) != int(meta.get("size") or -1):
        raise OutputError(f"page copy incomplete {len(data)}/{meta.get('size')} bytes")
    check_response(200, meta.get("contentType", ""), None, data)
    return data


async def _page_download(cdp, src: str, log_cb: Callable) -> Result:
    """Page fetch into a slot + sliced read; (ok, bytes, ctype | reason)."""
    key = uuid.uuid4().hex
    meta = _as_dict(await cdp.evaluate(f";({JS_FETCH_TO_SLOT})({json.dumps(src)}, {json.dumps(key)})"))
    if not meta.get("ok"):
        return False, b"", f"page download failed: {meta.get('error') or _no_result(cdp)}"
    data = await _read_slot(cdp, key, meta)
    log_cb(f"Page download {len(data)} bytes via {meta.get('method')} "
           f"({-(-int(meta['b64len']) // CHUNK_CHARS)} slice(s))", "success")
    return True, data, str(meta.get("contentType") or "")


async def _browser_download(cdp, src: str, log_cb: Callable) -> Result:
    """Heal a closed socket first, then the sliced page download."""
    try:
        await heal_link(cdp, log_cb)
        return await _page_download(cdp, src, log_cb)
    except (LinkLost, OutputError, binascii.Error, ValueError) as exc:
        return False, b"", f"page download failed: {exc}"


async def _python_first(src: str, log_cb: Callable) -> Result:
    """http(s) only: the Python fetch; a refusal is logged and handed to the page."""
    if not src.startswith(("http://", "https://")):
        return False, b"", ""
    ok, data, info = await _python_download(src, log_cb)
    if not ok:
        log_cb(f"{info} — trying the page", "warn")
    return ok, data, info


async def download_image(cdp, src: str, log_cb: Callable) -> Result:
    """(ok, bytes, content_type) — or (False, b"", reason naming every method tried)."""
    if src.startswith("data:"):
        return _decode_data_url(src)
    first = await _python_first(src, log_cb)
    second = first if first[0] else await _browser_download(cdp, src, log_cb)
    if second[0]:
        return second
    msg = f"All methods failed for {src[:120]}: " + "; ".join(r[2] for r in (first, second) if r[2])
    log_cb(msg, "warn")
    return False, b"", msg
