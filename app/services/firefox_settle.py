"""How a Firefox page is settled when a job saved nothing (steps 14–16).

Chrome's `finish_page_after_job` counts the job and cools the tab down. A failed
or uncertain Firefox job must not be cooled: the macro may have left a native
file dialog, a half-typed composer or a security dialog on the page, and the
in-flight evidence (the result image, the submit token) is exactly what a human
has to look at. Both settles therefore keep the page in the pool in a state that
refuses the next job — only the operator's reset clears it.
"""

from typing import Any

from ..browser.page_status import PageStatus

REVIEW_NOTE = "needs review — in-flight evidence kept"
WAITING = (PageStatus.WAITING_CAPTCHA, PageStatus.WAITING_GENERATION)


def _label(pool: Any, tab_id: str) -> str:
    """Readable tab handle for log lines (same shape as the cooldown lane)."""
    try:
        page = pool.get_page(tab_id)
    except Exception:
        page = None
    alias = getattr(page, "alias", "") if page is not None else ""
    return alias or str(tab_id)[:12]


def _publish(bridge, text: str) -> None:
    """Emit the pool status, then say it once in the log — never fatal."""
    try:
        bridge._emit_pool_status()
    except Exception:
        pass
    try:
        bridge._log(text, "warn")
    except Exception:
        pass


async def reset_page(bridge, pool, tab_id: str) -> tuple:
    """The Firefox New-chat reset through its own Ui.Vision macro (step 15).

    Only a pooled Firefox page has a macro to click; anything else keeps the
    lane's honest message, and a cancel stops before the click.
    """
    if getattr(bridge, "_cancel_requested", False):
        return False, "cancelled — no reset"
    try:
        page = pool.get_page(tab_id)
    except Exception:
        page = None
    if page is None or getattr(page, "browser", "") != "firefox":
        return False, "no CDP controller — Firefox lane (New-chat reset not applicable)"
    from .firefox_lane import reset_page as macro_reset
    try:
        return await macro_reset(bridge, page)
    except Exception as exc:
        return False, str(exc)


def settle_failed(pool, bridge, tab_id: str, note: str = "") -> None:
    """A failed job leaves its page to a human: error state, no cooldown (step 14).

    Cooling the tab would only hide whatever the macro left behind, and handing
    it a second job would stack a second unknown state on the first.
    """
    reason = note or "the job failed"
    try:
        pool.mark_error(tab_id, reason)
    except Exception:
        pass
    _publish(bridge, f"🛑 Page {_label(pool, tab_id)} left in error — {reason} "
                     f"(no cooldown, no new job until reset)")


def settle_for_review(pool, bridge, tab_id: str, note: str = "") -> None:
    """Uncertain output keeps the page and its evidence for a human (step 16).

    A page already waiting on the operator keeps that state — the instruction to
    solve a captcha outranks "error" — everything else becomes a pool error.
    """
    try:
        page = pool.get_page(tab_id)
        if getattr(page, "status", None) not in WAITING:
            pool.mark_error(tab_id, note or REVIEW_NOTE)
    except Exception:
        pass
    _publish(bridge, f"🛑 Page {_label(pool, tab_id)} kept for review — "
                     f"needs_review: no reset, no cooldown, no new job")
