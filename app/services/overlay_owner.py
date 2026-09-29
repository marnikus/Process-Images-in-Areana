"""Stable owner keys and job-owned watcher overlay requests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OverlayRequest:
    """Display fields for one temporary job overlay."""
    message: str
    kind: str
    timeout_sec: int
    sub: str = ""


def job_overlay_owner(ctx) -> str:
    """Return a distinct job/tab key shared by that job's overlay show/hide calls."""
    tab_id = str(getattr(ctx, "tab_id", "") or "unknown")
    job_id = str(getattr(ctx, "job_id", "") or getattr(ctx, "corr_id", "")
                 or getattr(ctx, "source", "job"))
    return f"job:{job_id}:{tab_id}"


async def show_job_overlay(ctx: Any, request: OverlayRequest) -> bool:
    """Show through the controller's spec API, with a legacy fake-CDP adapter."""
    from app.browser.dom_highlight import WatcherOverlaySpec
    owner = WatcherOverlaySpec(request.message, request.kind, request.timeout_sec,
                               request.sub, job_overlay_owner(ctx))
    from app.browser.cdp_arena import CDPArenaController
    if isinstance(ctx.ctrl, CDPArenaController):
        return await ctx.ctrl.show_watcher_overlay(owner)
    return await ctx.ctrl.show_watcher_overlay(
        owner.message, kind=owner.kind, timeout_sec=owner.timeout_sec,
        sub=owner.sub, owner_key=owner.owner_key)
