"""Post-generation reset — click New Chat, wait for full page load.

Spec 01: after each job the tab returns to a clean new chat; the tab is
marked ready only after the page is fully loaded. Clicks go through the
shared visual runner (RULE 1); every step is reported (RULE 2); selectors
are semantic-first (RULE 21). When the click fails or the page never gets
clean, the reset opens the New Chat page itself — `Page.navigate` to the
link's own path on the tab's origin, a full page restart — and waits for
the same proof (I-69). A page that stopped answering (a timed-out probe
and no answer to a 3 s ping) is told as such and skips the 30 s probes
(I-71). Imports: same layer only.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from . import page_recovery
from .probe_selectors import new_chat_path, new_chat_selectors, textarea_primary
from .visual_click import ClickRequest, find_and_click

# (selector, label_selector, match_text) — semantic href first, no classes.
# Selectors come from site_adapter (RULE 21); the text-proof strategy stays
# here: the two semantic entries must show the "New Chat" label, the
# structural fallback clicks on shape alone.
_NC_SELS = new_chat_selectors()
NEW_CHAT_CANDIDATES = (
    (_NC_SELS[0], "span", "New Chat"),
    (_NC_SELS[1], "span", "New Chat"),
    (_NC_SELS[2], "", ""),
)


@dataclass
class ResetCtx:
    """Context to keep params small (RULE 16)."""

    ctrl: Any
    client: Any
    engine: Any = None
    timeout_sec: float = 30.0
    cancel_check: Optional[Callable[[], bool]] = None


_PAGE_LOADED_TEMPLATE = """;(() => {
  try {
    const ta = document.querySelector(__TEXTAREA_PRIMARY__);
    const rs = document.readyState;
    return {complete: rs === 'complete', readyState: rs,
            hasTextarea: !!ta && ta.offsetParent !== null};
  } catch (e) { return {complete: false, error: String(e)}; }
})()"""

_COMPOSER_EMPTY_TEMPLATE = """;(() => {
  try {
    const ta = document.querySelector(__TEXTAREA_PRIMARY__);
    if (!ta) return {empty: false, len: -1};
    return {empty: ta.value.length === 0, len: ta.value.length};
  } catch (e) { return {empty: false, error: String(e)}; }
})()"""


def build_page_loaded_js() -> str:
    """Probe: document complete + composer textarea present."""
    return _PAGE_LOADED_TEMPLATE.replace("__TEXTAREA_PRIMARY__", repr(textarea_primary()))


def build_composer_empty_js() -> str:
    """Probe: new-chat composer is clean (empty value)."""
    return _COMPOSER_EMPTY_TEMPLATE.replace("__TEXTAREA_PRIMARY__", repr(textarea_primary()))


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
    """Try candidates in order via the visual runner; a page that stopped answering ends it (I-71)."""
    for candidate in NEW_CHAT_CANDIDATES:
        if await page_recovery.still_frozen(ctx.client):   # no more 30 s FIND probes
            return False, page_recovery.unresponsive_text(ctx.client)
        if await _try_candidate(ctx, candidate) == "ok":
            return True, candidate[0]
    return False, "new-chat button not found"


async def _try_candidate(ctx: ResetCtx, candidate: tuple) -> str:
    """One (selector, label, text) candidate through the visual runner: its result, or 'error'."""
    selector, label_selector, match_text = candidate
    req = ClickRequest(selector=selector, label_selector=label_selector,
                       match_text=match_text, label="New Chat")
    try:
        return await find_and_click(ctx.client, req, engine=ctx.engine)
    except Exception as e:
        _report(ctx.engine, f"New Chat click error {selector}: {e}", "warn")
        return "error"


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
    if await page_recovery.still_frozen(ctx.client):       # a 3 s ping keeps the deadline honest
        return False, page_recovery.unresponsive_text(ctx.client)
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
    """Click New Chat and wait for the load; a failed click or load opens the page directly."""
    _report(ctx.engine, "↩ Resetting to new chat after generation", "info")
    ok, why = await _click_and_wait(ctx)
    if not ok and not _is_cancelled(ctx):
        _report(ctx.engine, f"↩ New Chat did not work ({why}) — opening {new_chat_path()} directly", "warn")
        ok, detail = await _open_new_chat(ctx)
        why = detail if ok else f"{why}; direct open: {detail}"
    return _finish_reset(ctx, ok, why)


async def _click_and_wait(ctx: ResetCtx) -> tuple[bool, str]:
    """The normal way back: click the sidebar link, then the readiness proof."""
    clicked, why = await _click_new_chat(ctx)
    if not clicked:
        return False, why
    _report(ctx.engine, f"↩ New Chat clicked ({why}), waiting for load", "info")
    return await _wait_page_loaded(ctx)


def _finish_reset(ctx: ResetCtx, ok: bool, reason: str) -> tuple[bool, str]:
    """The one closing line of a reset (RULE 2)."""
    _report(ctx.engine, f"↩ New-chat reset {'ready' if ok else 'failed'}: {reason}",
            "success" if ok else "error")
    return ok, reason


async def _open_new_chat(ctx: ResetCtx) -> tuple[bool, str]:
    """Restart the tab on the New Chat page (`Page.navigate`), then the same readiness proof."""
    url, why = await _new_chat_url(ctx.client)
    if not url:
        return False, why
    try:
        await ctx.client.send("Page.navigate", {"url": url}, timeout=15)
    except Exception as e:
        return False, f"navigation failed: {e}"
    return await _wait_page_loaded(ctx)


async def _new_chat_url(client: Any) -> tuple[str, str]:
    """`<tab origin><New Chat path>` from the browser's own history — works while the page JS is stuck."""
    try:
        hist = await client.send("Page.getNavigationHistory", {}, timeout=10)
        url = hist["entries"][hist["currentIndex"]]["url"]
    except Exception as e:
        return "", f"page address unknown ({e})"
    parts = urlsplit(str(url))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "", f"page address unknown ({url})"
    return f"{parts.scheme}://{parts.netloc}{new_chat_path()}", ""
