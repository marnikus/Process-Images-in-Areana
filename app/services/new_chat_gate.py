"""A job starts only on a verified NEW chat — otherwise New Chat first (I-74).

Owner request 2026-09-27: "the app does not check if the new job goes on a new
chat page or not. Verify if the web page is a new chat! If not, start a new
chat first." A job never navigates — it runs on whatever the tab shows, so a
failed post-job reset or a chat the user opened sent the next image into an
old conversation.

    verify (`chat_page.read_chat_page`, one 5 s check)
      new      → one line, the job starts
      not new  → the same New Chat reset a finished job uses (click the link,
      unknown    else open /image/direct), then verify AGAIN:
                   new      → the job starts
                   not new  → the job fails with every piece of evidence —
                              never a prompt submitted into an old chat (RULE 4)

Called by both job paths (sequential `batch_orchestrator._execute_image`,
parallel `multi_page_dispatcher._run_image_job`) before anything touches the
page — the parallel baseline included.

ideal-size: ~65 lines — one gate shared by both job paths; its own module so
neither runner file (437 / 499 lines) carries it twice.
"""
from __future__ import annotations

from typing import Any, Tuple

from app.browser.chat_page import read_chat_page
from app.browser.new_chat import ResetCtx, reset_to_new_chat

RESET_TIMEOUT_S = 30.0


async def ensure_new_chat(bridge: Any, client: Any, ctrl: Any) -> Tuple[bool, str]:
    """(True, '') when the tab is (or became) a new chat; (False, reason) otherwise."""
    is_new, why = await read_chat_page(client)
    if is_new:
        _log(bridge, "🆕 New chat verified — starting the job", "info")
        return True, ""
    _log(bridge, f"🆕 Not a new chat page ({why}) — starting a new chat first", "warn")
    reset_note = await _reset(bridge, client, ctrl)
    is_new, why = await read_chat_page(client)
    if is_new:
        _log(bridge, "🆕 New chat verified after the reset — starting the job", "success")
        return True, ""
    reason = f"Not a new chat page ({why}) — New Chat {reset_note}"
    _log(bridge, f"❌ {reason} — the job is not started", "error")
    return False, reason


async def _reset(bridge: Any, client: Any, ctrl: Any) -> str:
    """The post-job reset, worded for a job start; how it went, for the failure reason."""
    ctx = ResetCtx(ctrl=ctrl, client=client, engine=bridge, timeout_sec=RESET_TIMEOUT_S,
                   cancel_check=lambda: bool(getattr(bridge, "_cancel_requested", False)),
                   purpose="before the job")
    try:
        ok, detail = await reset_to_new_chat(ctx)
    except Exception as e:   # the gate never crashes a job — it fails it with words
        ok, detail = False, str(e)
    return "did not help" if ok else f"failed: {detail}"


def _log(bridge: Any, message: str, level: str) -> None:
    """One job-log line (RULE 2); a bridge without a log stays quiet."""
    log = getattr(bridge, "_log", None)
    if callable(log):
        log(message, level)
