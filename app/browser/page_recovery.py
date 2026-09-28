"""Transient page-context loss — detect and wait it out (B8).

A `Runtime.evaluate` that comes back with no value is not one condition.
The transport records why (`cdp.last_error` / `cdp.last_error_kind`):

    "js"        the probe itself threw          → a real answer, never retry
    "protocol"  Chrome refused the evaluate      → transient when the page is
                mid-reload/navigation ("Execution context was destroyed",
                "Cannot find default execution context", ...)
    "transport" the DevTools socket is gone      → transient: same tab, new
                socket (reconnect to the remembered ws URL)

Field case that motivated this (bugfix-verification.md §B8): the image was
generated and downloaded, then every probe on the tab answered nothing for
about a second — the post-download block, the job and the New-chat reset
all failed on the first empty answer although the page came straight back.

Public API
----------
evaluate_failure(cdp)             human reason for the last empty evaluate
is_transient_loss(cdp)            True when waiting/reconnecting can help
recover_page_context(cdp, report) wait (and reconnect) until the document answers
page_unresponsive(cdp)            I-71: the last evaluate timed out (page not answering)
page_answers(cdp) / still_frozen  I-71: a 3 s ping instead of another 30 s probe;
                                  I-72: a silent socket is re-dialled (cdp/liveness)
unresponsive_text(cdp)            I-71: 'page not answering (<transport reason>)'
page_check(cdp, js)               I-73: a page check waits 5 s, not 30 s
unanswered_diag(diag)             I-78: a poll that got no answer is not a state
await_page_answer(cdp, budget_s)  I-78: bounded wait for a page that stopped
                                  answering to answer a ping again
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

log = logging.getLogger("arena")

CHECK_TIMEOUT_S = 5.0
RECOVERY_ATTEMPTS = 3
RECOVERY_DELAY_S = 1.0
RECOVERY_SETTLE_S = 1.0

# Chrome's wording for "the frame is between two documents right now".
TRANSIENT_MARKERS = (
    "execution context was destroyed",
    "cannot find default execution context",
    "cannot find context with specified id",
    "inspected target navigated or closed",
    "target closed",
    "session with given id not found",
)
# A hung page answers late, not never — retrying a 30 s timeout is not recovery.
NON_TRANSIENT_MARKERS = ("timed out",)

Reporter = Callable[[str, str], None]
_READY_JS = "(function(){try{return document.readyState}catch(e){return ''}})()"


def _noop(_msg: str, _level: str = "info") -> None:
    return None


async def page_check(cdp, js: str):
    """A page check waits CHECK_TIMEOUT_S, not the 30 s command default (I-73).

    Measured in Chrome on a 5,305-node chat page: the output check 56 ms, the
    Watcher probe 2 ms, the error scan 8 ms. A check still unanswered after 5 s
    means the page is busy — ask again soon instead of sitting out 30 s.
    """
    return await cdp.evaluate(js, timeout=CHECK_TIMEOUT_S)


def evaluate_failure(cdp) -> str:
    """Human reason recorded by the transport for the last empty evaluate."""
    return str(getattr(cdp, "last_error", "") or "")


def is_transient_loss(cdp) -> bool:
    """True when the last empty evaluate is worth waiting/reconnecting for."""
    kind = str(getattr(cdp, "last_error_kind", "") or "")
    reason = evaluate_failure(cdp).lower()
    if any(marker in reason for marker in NON_TRANSIENT_MARKERS):
        return False
    if kind == "transport":
        return True
    if kind == "protocol":
        return any(marker in reason for marker in TRANSIENT_MARKERS)
    return False


async def _reconnect_if_closed(cdp, report: Reporter) -> None:
    """Socket closed under us: re-attach to the SAME tab (never re-pick tabs)."""
    url = str(getattr(cdp, "_current_ws_url", "") or "")
    if getattr(cdp, "is_connected", True) or not url:
        return
    connect: Optional[Callable[[str], Awaitable[bool]]] = getattr(cdp, "connect", None)
    if connect is None:
        return
    report(f"🔌 CDP socket closed — reconnecting to the same tab {url[-24:]}", "warn")
    try:
        ok = await connect(url)
    except Exception as exc:  # connect() reports its own details
        ok = False
        log.warning("page_recovery reconnect raised: %s", exc)
    report("🔌 reconnected" if ok else "🔌 reconnect failed", "info" if ok else "warn")


async def _document_answers(cdp) -> bool:
    """One cheap probe: the page has a live document again."""
    try:
        state = await page_check(cdp, _READY_JS)     # I-73 budget: 5 s, not the 30 s default
    except Exception:
        return False
    return state in ("interactive", "complete")


async def recover_page_context(cdp, report: Optional[Reporter] = None,
                               attempts: int = RECOVERY_ATTEMPTS,
                               delay_s: float = RECOVERY_DELAY_S) -> bool:
    """Wait for the page context to come back after a transient loss.

    Returns True once `document.readyState` answers again (plus a short
    settle so a reloaded SPA can mount); False after `attempts` rounds.
    """
    say = report or _noop
    reason = evaluate_failure(cdp)[:90] or "no answer from the page"
    for attempt in range(1, attempts + 1):
        say(f"⏳ page context unavailable ({reason}) — waiting {delay_s:g}s "
            f"(attempt {attempt}/{attempts})", "warn")
        await asyncio.sleep(delay_s)
        await _reconnect_if_closed(cdp, say)
        if await _document_answers(cdp):
            await asyncio.sleep(RECOVERY_SETTLE_S)
            say("✅ page context is back — retrying", "info")
            return True
    say(f"❌ page context did not come back after {attempts} attempts ({reason})", "error")
    return False


# --- I-71: a page that stopped answering ---------------------------------
# Owner log 2026-09-27: after the page stopped answering, every output poll
# cost ~90 s (security gate + check + error scan, 30 s timeout each) and the
# New Chat reset hung on the same 30 s probes. Once one evaluate has timed
# out, callers ask a 3 s ping first instead of queueing more 30 s probes.
# Measured in Chrome: neither `Page.reload` nor a same-site `Page.navigate`
# rescues a page whose main thread is stuck — only waiting does; a blocking
# JavaScript dialog is answered by `cdp.dialogs` (see `cdp/dialogs.py`).
PING_TIMEOUT_S = 3.0
AWAIT_ANSWER_S = 20.0    # I-78: how long the rescue waits for a silent page to answer again
AWAIT_POLL_S = 1.0       # its ping cadence (module constants: tests shorten them)
_PING = {"expression": "1", "returnByValue": True}


def page_unresponsive(cdp) -> bool:
    """True when the last evaluate on this connection timed out (the page did not answer)."""
    kind = str(getattr(cdp, "last_error_kind", "") or "")
    return kind == "transport" and "timed out" in evaluate_failure(cdp).lower()


async def page_answers(cdp, timeout_s: Optional[float] = None) -> bool:
    """One cheap ping; an answer clears the timed-out record (the page is back)."""
    from .cdp.dialogs import close_open_dialog
    await close_open_dialog(cdp)
    try:
        await cdp.send("Runtime.evaluate", dict(_PING), timeout=timeout_s or PING_TIMEOUT_S)
    except Exception:
        return False
    cdp.last_error, cdp.last_error_kind = "", ""
    return True


async def still_frozen(cdp) -> bool:
    """Timed out before, no answer to a 3 s ping, and a fresh socket could not revive it (I-72)."""
    if not page_unresponsive(cdp) or await page_answers(cdp):
        return False
    from .cdp.liveness import revive_silent_socket
    return not await revive_silent_socket(cdp)


def unanswered_diag(diag) -> bool:
    """A poll that got no answer (`page_unresponsive`) is unknown — never read as a state (I-78)."""
    return str((diag or {}).get("reason") or "") == "page_unresponsive"


async def await_page_answer(cdp, budget_s: Optional[float] = None,
                            poll_s: Optional[float] = None) -> bool:
    """Wait (bounded) for a page that stopped answering to answer a ping again (I-78).

    A page that timed out once is not gone — it answers again when its main thread
    frees (I-73), so the caller gets this one window instead of giving up on the image
    the page may still be showing. A wedged socket gets its re-dial inside the window
    (I-72). Bounded: an answer, or False when the budget runs out.
    """
    deadline = time.monotonic() + max(0.0, AWAIT_ANSWER_S if budget_s is None else budget_s)
    wait = AWAIT_POLL_S if poll_s is None else poll_s
    while True:
        if await page_answers(cdp):
            return True
        if time.monotonic() >= deadline:
            return False
        await _ask_again(cdp)
        await asyncio.sleep(min(wait, max(0.0, deadline - time.monotonic())))


async def _ask_again(cdp) -> None:
    """One bounded re-dial attempt inside the wait (never raises)."""
    from .cdp.liveness import revive_silent_socket
    try:
        await revive_silent_socket(cdp)
    except Exception:
        pass


def unresponsive_text(cdp) -> str:
    """'page not answering (<transport reason>; last message 34 s ago: …)'."""
    from .cdp.liveness import rx_text
    return f"page not answering ({evaluate_failure(cdp)[:160] or 'no reply'}; {rx_text(cdp)})"
