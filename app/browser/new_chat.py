"""Post-generation reset — click New Chat, wait for full page load.

Spec 01: after each job the tab returns to a clean new chat; the tab is
marked ready only after the page is fully loaded. Clicks go through the
shared visual runner (RULE 1); every step is reported (RULE 2); selectors
are semantic-first (RULE 21). Imports: same layer only.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .visual_click import ClickRequest, find_and_click

# (selector, label_selector, match_text) — semantic href first, no classes.
NEW_CHAT_CANDIDATES = (
    ('a[href="/image/direct"]', "span", "New Chat"),
    ('li[data-sidebar="menu-item"] a[href="/image/direct"]', "span", "New Chat"),
    ('a[data-sidebar="menu-button"][href="/image/direct"]', "", ""),
)


@dataclass
class ResetCtx:
    """Context to keep params small (RULE 16)."""

    ctrl: Any
    client: Any
    engine: Any = None
    timeout_sec: float = 30.0
    cancel_check: Optional[Callable[[], bool]] = None


def build_page_loaded_js() -> str:
    """Probe: document complete + composer textarea present."""
    return """;(() => {
  try {
    const ta = document.querySelector('textarea[name="message"]');
    const rs = document.readyState;
    return {complete: rs === 'complete', readyState: rs,
            hasTextarea: !!ta && ta.offsetParent !== null};
  } catch (e) { return {complete: false, error: String(e)}; }
})()"""


def build_composer_empty_js() -> str:
    """Probe: new-chat composer is clean (empty value)."""
    return """;(() => {
  try {
    const ta = document.querySelector('textarea[name="message"]');
    if (!ta) return {empty: false, len: -1};
    return {empty: ta.value.length === 0, len: ta.value.length};
  } catch (e) { return {empty: false, error: String(e)}; }
})()"""


def _report(engine: Any, message: str, level: str = "info"):
    """Report via engine.report() or bridge._log() (RULE 2)."""
    if engine is None:
        return
    for attr in ("report", "_log"):
        if hasattr(engine, attr):
            try:
                getattr(engine, attr)(message, level)
            except Exception:
                pass


def _as_dict(raw: Any) -> dict:
    """CDP evaluate may return a dict or a JSON string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


async def _is_document_complete(client: Any) -> bool:
    """True when readyState complete and textarea visible."""
    try:
        raw = await client.evaluate(build_page_loaded_js())
    except Exception:
        return False
    data = _as_dict(raw)
    return bool(data.get("complete") and data.get("hasTextarea", True))


async def _is_composer_empty(client: Any) -> bool:
    """True when the new-chat composer holds no text."""
    try:
        raw = await client.evaluate(build_composer_empty_js())
    except Exception:
        return False
    return bool(_as_dict(raw).get("empty"))


async def _click_new_chat(ctx: ResetCtx) -> tuple[bool, str]:
    """Try candidates in order via the visual runner."""
    for selector, label_selector, match_text in NEW_CHAT_CANDIDATES:
        req = ClickRequest(selector=selector, label_selector=label_selector,
                           match_text=match_text, label="New Chat")
        try:
            result = await find_and_click(ctx.client, req, engine=ctx.engine)
        except Exception as e:
            _report(ctx.engine, f"New Chat click error {selector}: {e}", "warn")
            continue
        if result == "ok":
            return True, selector
    return False, "new-chat button not found"


def _is_cancelled(ctx: ResetCtx) -> bool:
    """Cancel honour (RULE 7)."""
    try:
        return bool(ctx.cancel_check and ctx.cancel_check())
    except Exception:
        return False


# Fresh new chat has no file/output yet — their absence is not failure.
# prompt/send/Security reasons still block (composer proof required anyway).
_FRESH_CHAT_OK = frozenset({
    "file not found", "file not visible",
    "output not found", "output not visible",
})


def _fresh_chat_ready(ready: bool, reasons) -> bool:
    """Ready gate that tolerates missing file/output on a fresh chat."""
    if ready:
        return True
    if not reasons:
        return False
    return all(r in _FRESH_CHAT_OK for r in (reasons or []))


async def _check_ready(ctx: ResetCtx) -> tuple[bool, str]:
    """One readiness probe: (ready, status-note for timeout messages)."""
    if not await _is_document_complete(ctx.client):
        return False, "document not complete"
    try:
        ready, reasons = await ctx.ctrl.is_page_ready()
    except Exception as e:
        return False, f"readiness check failed: {e}"
    if _fresh_chat_ready(ready, reasons) and await _is_composer_empty(ctx.client):
        return True, "new chat ready"
    return False, f"ready={ready} reasons={reasons}"


async def _wait_page_loaded(ctx: ResetCtx) -> tuple[bool, str]:
    """Poll until document complete + page ready + composer empty."""
    deadline = time.monotonic() + max(1.0, float(ctx.timeout_sec or 30))
    last = "starting"
    while True:
        if _is_cancelled(ctx):
            return False, "cancelled"
        ok, last = await _check_ready(ctx)
        if ok:
            return True, last
        if time.monotonic() >= deadline:
            return False, f"timeout waiting for new chat ({last})"
        await asyncio.sleep(min(1.0, max(0.05, deadline - time.monotonic())))


async def reset_to_new_chat(ctx: ResetCtx) -> tuple[bool, str]:
    """Click New Chat, then wait for the full page load."""
    _report(ctx.engine, "↩ Resetting to new chat after generation", "info")
    clicked, click_info = await _click_new_chat(ctx)
    if not clicked:
        _report(ctx.engine, f"↩ New-chat reset failed: {click_info}", "error")
        return False, click_info
    _report(ctx.engine, f"↩ New Chat clicked ({click_info}), waiting for load", "info")
    ok, reason = await _wait_page_loaded(ctx)
    _report(ctx.engine, f"↩ New-chat reset {'ready' if ok else 'failed'}: {reason}",
            "success" if ok else "error")
    return ok, reason
