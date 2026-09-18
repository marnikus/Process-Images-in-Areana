"""Probe I/O for the recorder: install/buffer-flush/snapshot over CDP.

Every call is fail-open (RULE 9): a dead page or dead CDP yields empty
results, never an exception into the captcha flow. Buffer payloads are
bounded and field-whitelisted before they touch the store (RULE 13).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from app.browser.recording_probes import (build_flush_js, build_netwrap_js,
                                          build_observer_js, build_snapshot_js)

from .sanitizer import bound_str, redact_url

MAX_URL = 300
MAX_SEL = 80
MAX_ATTR = 40


def _parse(raw: Any) -> Dict[str, Any]:
    try:
        res = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except Exception:
        return {}
    return res if isinstance(res, dict) else {}


async def install(ctrl: Any) -> str:
    """Install mutation observer + network wrapper; returns last error ('' ok)."""
    err = ""
    for probe in (build_observer_js(), build_netwrap_js()):
        try:
            await ctrl.cdp.evaluate(probe)
        except Exception as e:
            err = str(e)
    return err


async def snapshot_html(ctrl: Any) -> str:
    """Full redacted DOM snapshot as HTML ('' when unavailable)."""
    try:
        res = _parse(await ctrl.cdp.evaluate(build_snapshot_js()))
    except Exception:
        return ""
    return str(res.get("html") or "") if res.get("ok") else ""


async def flush_into(ctrl: Any, store: Any, session: Any) -> None:
    """Drain page-side mutation/network buffers into the event log."""
    try:
        res = _parse(await ctrl.cdp.evaluate(build_flush_js()))
    except Exception:
        return
    for m in res.get("mutations") or []:
        store.append_event(session, "mutation", bound_mutation(m))
        session.bump("mutations")
    for r in res.get("requests") or []:
        store.append_event(session, "network", bound_request(r))
        session.bump("requests")


def bound_mutation(m: Any) -> Dict[str, Any]:
    m = m if isinstance(m, dict) else {}
    return {"ts": m.get("ts"), "mut": bound_str(m.get("mut"), 12),
            "sel": bound_str(m.get("sel"), MAX_SEL),
            "added": int(m.get("added") or 0),
            "removed": int(m.get("removed") or 0),
            "attr": bound_str(m.get("attr"), MAX_ATTR)}


def bound_request(r: Any) -> Dict[str, Any]:
    r = r if isinstance(r, dict) else {}
    url = redact_url(str(r.get("url") or ""))[:MAX_URL]
    host = url.split("/")[2] if url.count("/") >= 2 else ""
    return {"ts": r.get("ts"), "via": bound_str(r.get("via"), 6),
            "method": bound_str(r.get("method"), 8), "url": url,
            "host": host, "status": int(r.get("status") or 0)}
