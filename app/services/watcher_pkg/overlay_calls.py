"""Adapt an owner-aware Watcher overlay to modern controllers or legacy fakes."""
from __future__ import annotations

from app.browser.cdp_arena import CDPArenaController


async def show_overlay(cdp, spec):
    if isinstance(cdp, CDPArenaController):
        return await cdp.show_watcher_overlay(spec)
    return await _show_legacy(cdp, spec)


async def _show_legacy(cdp, spec):
    options = {"kind": spec.kind, "timeout_sec": spec.timeout_sec, "owner_key": spec.owner_key}
    if spec.sub:
        options["sub"] = spec.sub
    return await cdp.show_watcher_overlay(spec.message, **options)
