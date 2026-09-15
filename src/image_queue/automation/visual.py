"""Actual retained FIND/staged CLICK/dispatch probes with strict unique-root guards.

Library only: no live adapter or GUI execution command is registered.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from image_queue.domain.settings import HighlightSettings
from image_queue.domain.validation import ContractError

Evaluate = Callable[[str], Awaitable[str]]
PROBES = json.loads((Path(__file__).parents[1] / "ui/visual/probes.json").read_text())
CLEAR = """JSON.stringify((()=>{
document.querySelectorAll('[data-cf-highlight]').forEach(e=>e.remove());
window.__cfStash=null;window.__iqTarget=null;return {cleared:true};})())"""


def build_probe(selector: str, phase: str, settings: HighlightSettings) -> str:
    if not isinstance(selector, str) or not selector.strip() or len(selector) > 2000:
        raise ContractError("A bounded, scoped selector is required")
    if phase not in ("find", "stage", "click"):
        raise ContractError("Unknown visual phase")
    fields = {
        "selector": json.dumps(selector),
        "label_selector": "null",
        "match_text": "null",
        "exact": "true",
        "highlight": json.dumps(_enabled(settings) and phase != "click"),
        "color": json.dumps("#ff2d2d" if phase == "find" else "#ff9500"),
        "caption": json.dumps("FOUND" if phase == "find" else "CLICK"),
        "hms": settings.highlight_ms,
        "stash": "__cfStash",
        "maxcand": 0,
        "click_selector": "null",
        "do_click": json.dumps(phase == "click"),
    }
    body = PROBES["_FIND_BODY" if phase == "find" else "_CLICK_BODY"] % fields
    body = _guard(selector, phase) + body
    if phase == "find":
        body += "\nwindow.__iqTarget = window.__cfStash;"
    return str(
        PROBES["_PROBE_JS"] % {"out": PROBES["out"], "helpers": PROBES["_HELPERS_JS"], "body": body}
    )


def _guard(selector: str, phase: str) -> str:
    root = (
        f"document.querySelectorAll({json.dumps(selector)})"
        if phase == "find"
        else "[window.__cfStash]"
    )
    return f"""
    var roots = {root};
    if (roots.length !== 1 || !roots[0]) throw Error('unique target required');
    var guardRoot = roots[0];
    if ({json.dumps(phase != "find")} && guardRoot !== window.__iqTarget)
      throw Error('target changed');
    if (!guardRoot.isConnected) throw Error('detached target');
    for (var parent = guardRoot; parent; parent = parent.parentElement) {{
      var style = getComputedStyle(parent);
      if (style.display === 'none' || style.visibility === 'hidden' ||
          style.opacity === '0' || parent.inert)
        throw Error('hidden target');
    }}
    if (guardRoot.disabled || guardRoot.getAttribute('aria-disabled') === 'true')
      throw Error('disabled target');
    """


async def _phase(evaluate: Evaluate, script: str, expected: str) -> None:
    async with asyncio.timeout(5):
        raw = await evaluate(script)
    try:
        result = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ContractError("Visual probe returned invalid data") from exc
    if not isinstance(result, dict) or result.get("error") or result.get(expected) is not True:
        raise ContractError("Visual phase failed; no success inferred")


async def find_and_click(evaluate: Evaluate, selector: str, settings: HighlightSettings) -> None:
    """Retained phase order/pause, no speed multiplier, no retry or success-of-job claim."""
    dispatched = False
    try:
        await _phase(evaluate, build_probe(selector, "find", settings), "clickable")
        if settings.highlight_enabled and settings.highlight_ms > 0:
            await asyncio.sleep(settings.confirm_pause_ms / 1000)
        await _phase(evaluate, build_probe(selector, "stage", settings), "clickable")
        if settings.highlight_enabled and settings.highlight_ms > 0:
            await asyncio.sleep(0.250)
        await _phase(evaluate, build_probe(selector, "click", settings), "clicked")
        dispatched = True
    finally:
        try:
            async with asyncio.timeout(5):
                await evaluate(STASH_CLEAR if dispatched else CLEAR)
        except (OSError, TimeoutError, ContractError):
            pass  # cleanup failure never permits replay of an uncertain click


STASH_CLEAR = (
    "JSON.stringify((()=>{window.__cfStash=null;window.__iqTarget=null;return {cleared:true};})())"
)


def _enabled(settings: HighlightSettings) -> bool:
    return settings.highlight_enabled and settings.highlight_ms > 0
