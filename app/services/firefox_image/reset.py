"""New Chat on a Firefox worker after a saved job (I-65).

One native XClick of the same New Chat control Chrome uses, then a
clean-composer read-back. Never a CDP reset, and never a close of the
preexisting tab. A missing binary returns before any macro is written.

Imports: browser launch + sibling transport.
"""

from __future__ import annotations

from .transport import PhaseCall, firefox_ready, run_phase


async def reset_firefox_chat(pool, tab_id: str, bridge) -> tuple:
    """(ok, reason). Failure names firefox and does not pretend a CDP reset ran."""
    if not firefox_ready(bridge):
        return False, "no firefox binary for new chat"
    page = pool.get_page(tab_id) if pool is not None else None
    if page is None:
        return False, "firefox tab left the pool"
    reply = await run_phase(PhaseCall(bridge, page, "new_chat", {}))
    if reply.get("kind") != "ok":
        return False, f"firefox new chat: {reply.get('message') or reply.get('kind')}"
    data = reply.get("data") or {}
    if data.get("composer_empty") or data.get("page_ready"):
        return True, ""
    return False, "firefox new chat: composer not clean"
