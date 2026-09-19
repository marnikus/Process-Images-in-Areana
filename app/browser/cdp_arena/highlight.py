"""Arena highlight — extracted from cdp_arena.py (C3).

RULE18: file 150-300, func ≤20, CC≤10, methods≤15, params≤4.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("arena")


@dataclass
class HighlightSpec:
    color: str = "#FF0000"
    duration_ms: int = 2000
    caption: str = ""


@dataclass
class WatcherOverlaySpec:
    message: str = "wait for finish generation"
    kind: str = "generation"
    timeout_sec: int = 600
    sub: str = ""


def _parse_rect(raw) -> Optional[dict]:
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict) and data.get("rect"):
            return data.get("rect")
    except Exception:
        pass
    return None


async def _try_highlight_probe(cdp, selector: str, spec: HighlightSpec) -> Optional[dict]:
    try:
        from ..dom_highlight import build_highlight_probe
        from ..probe_requests import HighlightSpec as ProbeSpec
        probe_spec = ProbeSpec(color=spec.color, caption=spec.caption or selector[:40],
                               highlight_ms=spec.duration_ms, clear_first=True)
        js = build_highlight_probe(selector, probe_spec)
        raw = await cdp.evaluate(js)
        return _parse_rect(raw)
    except Exception as e:
        log.debug(f"probe highlight failed {e}")
        return None


async def _try_highlight_fallback(cdp, selector: str, spec: HighlightSpec) -> Optional[dict]:
    try:
        from ..dom_highlight import build_highlight_js
        js = build_highlight_js(selector, spec.color, spec.duration_ms, spec.caption, clear_first=True)
        raw = await cdp.evaluate(js)
        return _parse_rect(raw)
    except Exception as e:
        log.debug(f"fallback highlight failed {e}")
        return None


async def highlight_selector(cdp, selector: str, spec: HighlightSpec = None) -> dict | None:
    if spec is None:
        spec = HighlightSpec()
    rect = await _try_highlight_probe(cdp, selector, spec)
    if rect:
        return rect
    rect2 = await _try_highlight_fallback(cdp, selector, spec)
    if rect2:
        return rect2
    return {"x": 100, "y": 100, "width": 200, "height": 100}


async def highlight_selector_legacy(cdp, selector: str, color: str = "#FF0000",
                                    duration_ms: int = 2000, caption: str = "") -> dict | None:
    spec = HighlightSpec(color=color, duration_ms=duration_ms, caption=caption)
    return await highlight_selector(cdp, selector, spec)


async def clear_highlights(cdp):
    try:
        from ..dom_highlight import build_clear_js
        js = build_clear_js()
        await cdp.evaluate(js)
    except Exception as e:
        log.debug(f"clear failed {e}")


async def show_watcher_overlay(cdp, spec: WatcherOverlaySpec = None) -> bool:
    if spec is None:
        spec = WatcherOverlaySpec()
    try:
        from ..dom_highlight import build_watcher_overlay_js
        js = build_watcher_overlay_js(message=spec.message, kind=spec.kind,
                                      timeout_sec=spec.timeout_sec, sub=spec.sub)
        raw = await cdp.evaluate(js)
        if raw:
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                return bool(data.get("shown")) if isinstance(data, dict) else True
            except Exception:
                return True
        return False
    except Exception as e:
        log.debug(f"watcher overlay failed {e}")
        return False


async def show_watcher_overlay_legacy(cdp, message: str = "wait for finish generation",
                                      kind: str = "generation", timeout_sec: int = 600,
                                      sub: str = "") -> bool:
    spec = WatcherOverlaySpec(message=message, kind=kind, timeout_sec=timeout_sec, sub=sub)
    return await show_watcher_overlay(cdp, spec)


async def hide_watcher_overlay(cdp) -> bool:
    try:
        from ..dom_highlight import build_watcher_clear_js
        js = build_watcher_clear_js()
        await cdp.evaluate(js)
        return True
    except Exception as e:
        log.debug(f"hide watcher failed {e}")
        return False
