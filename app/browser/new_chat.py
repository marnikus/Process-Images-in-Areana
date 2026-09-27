"""Post-generation reset — click New Chat, wait for full page load; else restart the page.

Spec 01: after each job the tab returns to a clean new chat; the tab is
marked ready only after the page is fully loaded. Clicks go through the
shared visual runner (RULE 1); every step is reported (RULE 2); selectors
are semantic-first (RULE 21).

2026-09-27 D-4: both stages are time-boxed, so a page that stops answering
cannot hang the reset. When the click stage fails, the tab is navigated to
its New Chat page (`page_restart`) and the same clean-composer proof runs.
Imports: same layer only.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .page_recovery import LinkLost, heal_link
from .page_restart import restart_to_new_chat
from .probe_selectors import attachment_preview_selectors, new_chat_selectors, textarea_primary
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
STAGE_SLACK_S = 20.0  # each stage may take its load timeout + this, then it is cut


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

# Clean composer = no text AND no leftover attachment preview (2026-09-26): a
# stale preview would ride along with the next job's image.
_COMPOSER_EMPTY_TEMPLATE = """;(() => {
  try {
    const ta = document.querySelector(__TEXTAREA_PRIMARY__);
    if (!ta) return {empty: false, len: -1};
    let previews = 0;
    for (const sel of __PREVIEW_SELECTORS__) {
      for (const el of document.querySelectorAll(sel)) { if (el.offsetParent !== null) previews++; }
    }
    return {empty: ta.value.length === 0 && previews === 0, len: ta.value.length, previews: previews};
  } catch (e) { return {empty: false, error: String(e)}; }
})()"""


def build_page_loaded_js() -> str:
    """Probe: document complete + composer textarea present."""
    return _PAGE_LOADED_TEMPLATE.replace("__TEXTAREA_PRIMARY__", repr(textarea_primary()))


def build_composer_empty_js() -> str:
    """Probe: new-chat composer is clean (empty value, no attachment preview)."""
    return (_COMPOSER_EMPTY_TEMPLATE.replace("__TEXTAREA_PRIMARY__", repr(textarea_primary()))
            .replace("__PREVIEW_SELECTORS__", json.dumps(attachment_preview_selectors())))


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


async def _heal_first(ctx: ResetCtx) -> str:
    """A closed socket is re-attached to the same tab first; '' or why it could not be."""
    try:
        await heal_link(ctx.client, lambda m, l="info": _report(ctx.engine, m, l))
    except LinkLost as exc:
        return str(exc)
    return ""


async def _try_candidate(ctx: ResetCtx, candidate: tuple) -> bool:
    """One (selector, label_selector, match_text) through the visual runner."""
    selector, label_selector, match_text = candidate
    req = ClickRequest(selector=selector, label_selector=label_selector,
                       match_text=match_text, label="New Chat")
    try:
        return await find_and_click(ctx.client, req, engine=ctx.engine) == "ok"
    except Exception as e:
        _report(ctx.engine, f"New Chat click error {selector}: {e}", "warn")
        return False


async def _click_new_chat(ctx: ResetCtx) -> tuple[bool, str]:
    """Heal a closed socket, then try the candidates in order."""
    lost = await _heal_first(ctx)
    if lost:
        return False, lost
    for candidate in NEW_CHAT_CANDIDATES:
        if await _try_candidate(ctx, candidate):
            return True, candidate[0]
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


async def _bounded(ctx: ResetCtx, work, stage: str) -> tuple[bool, str]:
    """Run one stage within timeout_sec + STAGE_SLACK_S (a silent page cannot hang it)."""
    budget = max(1.0, float(ctx.timeout_sec or 30)) + STAGE_SLACK_S
    try:
        return await asyncio.wait_for(work, timeout=budget)
    except asyncio.TimeoutError:
        return False, f"{stage}: the page did not answer within {budget:.0f}s"


async def _click_and_wait(ctx: ResetCtx) -> tuple[bool, str]:
    """Stage 1: click New Chat (closed socket healed first), then the clean-composer proof."""
    clicked, click_info = await _click_new_chat(ctx)
    if not clicked:
        return False, click_info
    _report(ctx.engine, f"↩ New Chat clicked ({click_info}), waiting for load", "info")
    return await _wait_page_loaded(ctx)


async def _restart_and_wait(ctx: ResetCtx, why: str) -> tuple[bool, str]:
    """Stage 2: navigate the tab to its New Chat page, then the same proof."""
    _report(ctx.engine, f"🔄 New Chat did not open ({why}) — restarting the page", "warn")
    ok, info = await restart_to_new_chat(ctx.client)
    if not ok:
        return False, f"{why}; page restart failed: {info}"
    _report(ctx.engine, f"🔄 Page restarted at {info}, waiting for a clean composer", "info")
    ok, reason = await _wait_page_loaded(ctx)
    return ok, (f"after page restart: {reason}" if ok else f"{why}; after page restart: {reason}")


async def reset_to_new_chat(ctx: ResetCtx) -> tuple[bool, str]:
    """Click New Chat and prove a clean composer; else restart the page there (D-4)."""
    _report(ctx.engine, "↩ Resetting to new chat after generation", "info")
    ok, reason = await _bounded(ctx, _click_and_wait(ctx), "New Chat")
    if not ok and not _is_cancelled(ctx) and reason != "cancelled":
        ok, reason = await _bounded(ctx, _restart_and_wait(ctx, reason), "page restart")
    _report(ctx.engine, (f"↩ ✔ New chat open — clean composer confirmed ({reason})" if ok
                         else f"↩ New-chat reset failed: {reason}"), "success" if ok else "error")
    return ok, reason
