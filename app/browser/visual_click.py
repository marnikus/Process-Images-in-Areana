"""Shared visual-confirmation click runner — THE way blocks click elements (Arena).

Restored from Old App backend/visual_click.py, adapted for Arena.

Every action block that locates a DOM element and clicks it MUST go through
this module. It guarantees uniform, observable contract:

    Phase 1 FIND  — log success/failure, draw thin RED outline, pause.
    Phase 2 CLICK — log clickability, draw thin ORANGE outline, click.

Public API
----------
find_and_click(cdp, ClickRequest(...))
    Locate element (optionally by text of child) and click it.
    Legacy callers may pass knobs as kwargs.
find_and_click_exact(cdp, selector=..., label_selector=..., text=...)
    Same but exact text match.
"""

import asyncio
import dataclasses
import json
import logging
from dataclasses import dataclass
from typing import Optional

from app.browser.dom_highlight import (
    build_click_probe,
    build_find_probe,
    interpret_click,
    interpret_click_target,
    interpret_find,
)
from app.browser import page_recovery
from app.browser.probe_requests import (
    MATCH_CONTAINS,
    MATCH_EXACT,
    ClickProbeSpec,
    FindProbeSpec,
)

log = logging.getLogger("arena")

CLICK_PAUSE_MS = 250
# B8: an empty FIND/stage answer caused by a transient page-context loss
# (reload, navigation, closed socket) is recovered and re-probed this often.
PROBE_ATTEMPTS = 3


def _report(engine, message: str, level: str = "info") -> None:
    if engine is not None and hasattr(engine, "report"):
        try:
            engine.report(message, level)
        except Exception:
            pass
    # Also try _log if present (Bridge)
    if engine is not None and hasattr(engine, "_log"):
        try:
            engine._log(message, level)
        except Exception:
            pass


def _parse(raw) -> Optional[dict]:
    try:
        res = json.loads(raw) if raw else None
    except (json.JSONDecodeError, TypeError):
        return None
    return res if isinstance(res, dict) else None


@dataclass(frozen=True, slots=True)
class ClickRequest:
    """What to find, what to click, and how long to make user look."""

    selector: str = ""
    label_selector: str = ""
    match_text: str = ""
    match_mode: str = MATCH_CONTAINS
    click_enabled: bool = True
    click_selector: str = ""
    highlight_enabled: bool = True
    confirm_pause_ms: int = 700
    highlight_ms: int = 2000
    label: str = "element"

    @classmethod
    def from_kwargs(cls, **kwargs) -> "ClickRequest":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in kwargs.items() if k in known})

    def find_probe(self) -> str:
        return build_find_probe(
            self.selector,
            FindProbeSpec(
                label_selector=self.label_selector or None,
                match_text=self.match_text or None,
                match_mode=self.match_mode,
                highlight=self.highlight_enabled,
                highlight_ms=self.highlight_ms,
            ),
        )

    def staged_probe(self) -> str:
        return build_click_probe(
            self.click_selector or None,
            ClickProbeSpec(
                highlight=self.highlight_enabled,
                highlight_ms=self.highlight_ms,
                do_click=False,
            ),
        )

    def click_probe(self) -> str:
        return build_click_probe(
            self.click_selector or None,
            ClickProbeSpec(highlight=False, do_click=True),
        )

    def holds_confirmation(self) -> bool:
        return bool(self.highlight_enabled and self.confirm_pause_ms > 0)

    def click_target_description(self, find_result: dict) -> str:
        return (
            self.click_selector.strip()
            if self.click_selector
            else (find_result.get("target_desc") or "the found element")
        )


def _empty_reason(cdp) -> str:
    """Why the page answered nothing — the transport's record, else the old guess."""
    return page_recovery.evaluate_failure(cdp) or "page context unavailable?"


async def _probe_json(cdp, js: str, engine: Optional[object]) -> Optional[dict]:
    """Evaluate a JSON-returning probe; recover + retry on transient page loss.

    B8: one empty answer used to fail the block outright, even when the page
    was merely mid-reload for a second. Non-transient empties (the probe
    threw) still fail on the first answer — see page_recovery.is_transient_loss.
    """
    for attempt in range(1, PROBE_ATTEMPTS + 1):
        res = _parse(await cdp.evaluate(js))
        if res is not None:
            return res
        if attempt == PROBE_ATTEMPTS or not page_recovery.is_transient_loss(cdp):
            return None
        if not await page_recovery.recover_page_context(
                cdp, lambda m, lvl="info": _report(engine, m, lvl)):
            return None
    return None


async def find_phase(cdp, request: ClickRequest, engine: Optional[object] = None) -> Optional[dict]:
    _report(engine, f"🔍 FIND phase: searching {request.label}", "info")
    try:
        res = await _probe_json(cdp, request.find_probe(), engine)
    except Exception as exc:
        _report(engine, f"❌ FIND failed: CDP error during element search: {exc}", "error")
        log.error("visual_click CDP error (find): %s", exc)
        return None
    if res is None:
        _report(engine, f"❌ FIND failed: {request.label} — no data returned from the page ({_empty_reason(cdp)})", "error")
        return None
    _report(engine, f"🔍 Selector matched {int(res.get('total', 0) or 0)} node(s)", "info")
    msg, level = interpret_find(res, request.label)
    _report(engine, msg, level)
    if not res.get("found"):
        log.warning("FIND failed: %s", request.label)
        return None
    log.info("FIND success: %s (node #%s)", request.label, res.get("index"))
    return res


async def click_phase(cdp, request: ClickRequest, found: dict, engine: Optional[object] = None) -> str:
    if not request.click_enabled:
        _report(engine, "ℹ Click disabled for this block — find-only mode", "info")
        return "ok" if found.get("found") else "fail"
    if not found.get("visible"):
        _report(engine, f"❌ CLICK skipped: {request.label} was found but is not visible", "error")
        return "fail"

    target = request.click_target_description(found)
    _report(engine, f"🖱 CLICK phase: target = {target}", "info")
    pre = await _stage(cdp, request, engine)
    if pre is None or not pre.get("clickable"):
        return "fail"
    if request.highlight_enabled and CLICK_PAUSE_MS > 0:
        await asyncio.sleep(CLICK_PAUSE_MS / 1000.0)
    done = await _dispatch(cdp, request, engine)
    if done is None:
        return "fail"
    msg, level = interpret_click(done, request.label)
    _report(engine, msg, level)
    if done.get("clicked"):
        log.info("CLICK success: %s", request.label)
        return "ok"
    log.warning("CLICK failed: %s", request.label)
    return "fail"


async def _stage(cdp, request, engine) -> Optional[dict]:
    try:
        pre = await _probe_json(cdp, request.staged_probe(), engine)
    except Exception as exc:
        _report(engine, f"❌ CLICK failed: CDP error while resolving click target: {exc}", "error")
        return None
    if pre is None:
        _report(engine, f"❌ CLICK failed: no data returned while resolving click target ({_empty_reason(cdp)})", "error")
        return None
    if pre.get("error"):
        _report(engine, f"❌ CLICK failed: {pre['error']}", "error")
        return None
    msg, level = interpret_click_target(pre)
    _report(engine, msg, level)
    if not pre.get("clickable"):
        log.warning("CLICK target not clickable: %s", request.label)
        return None
    return pre


async def _dispatch(cdp, request, engine) -> Optional[dict]:
    try:
        raw = await cdp.evaluate(request.click_probe())
    except Exception as exc:
        _report(engine, f"❌ CLICK failed: CDP error during click: {exc}", "error")
        return None
    done = _parse(raw)
    if done is None:
        # Deliberately no recovery/retry here: the click may already have
        # landed before the context vanished — re-dispatching could double it.
        _report(engine, f"❌ CLICK failed: no data returned from the click ({_empty_reason(cdp)})", "error")
    return done


async def run_click(cdp, request: ClickRequest, engine: Optional[object] = None) -> str:
    if not request.selector or not str(request.selector).strip():
        _report(engine, "❌ `selector` is empty — configure the block first", "error")
        return "fail"
    found = await find_phase(cdp, request, engine)
    if found is None:
        return "fail"
    if request.holds_confirmation():
        hold_ms = request.confirm_pause_ms
        _report(engine, f"⏸ Holding {hold_ms} ms for visual confirmation…", "info")
        await asyncio.sleep(hold_ms / 1000.0)
    return await click_phase(cdp, request, found, engine)


async def find_and_click(cdp, request: Optional[ClickRequest] = None, engine: Optional[object] = None, **legacy) -> str:
    return await run_click(cdp, request or ClickRequest.from_kwargs(**legacy), engine=engine)


async def find_and_click_exact(cdp, *, text: str, **kw) -> str:
    kw.pop("match_mode", None)
    return await find_and_click(cdp, match_text=text, match_mode=MATCH_EXACT, **kw)
