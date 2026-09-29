# ideal-size: 90 lines reason=owner preservation owns probe + check that always changes together
"""Owner preservation — Arena account email must stay same across handover."""

from __future__ import annotations

import asyncio
from typing import Any


async def _read_owner_from_client(client: Any) -> str:
    """Probe account email from a tab's client ('' when unknown)."""
    try:
        from app.browser.owner_probe import build_owner_probe, interpret_owner
        from app.core.tab_alias import normalize_owner
        raw = await client.evaluate(build_owner_probe())
        return normalize_owner(interpret_owner(raw).get("email"))
    except Exception:
        return ""


async def _check_owner_preserved(move: Any) -> tuple[bool, str]:
    """Ensure new tab has same Arena account as old tab (profile-correct)."""
    if not move.old_owner:
        return True, ""
    new_owner = ""
    for _ in range(3):
        try:
            new_owner = await _read_owner_from_client(move.ctx.client)
        except Exception:
            new_owner = ""
        if new_owner:
            break
        await asyncio.sleep(0.5)
    if not new_owner:
        from .handover import _log
        _log(move, f"Owner probe empty for new tab {move.new.id[:12]} after retries — "
                    f"keeping {move.old_owner}", "info")
        return True, ""
    if new_owner.lower() == move.old_owner.lower():
        return True, ""
    return False, f"Owner mismatch: old {move.old_owner} vs new {new_owner} — wrong profile, rollback"


def _preserve_owner_after_move(pool: Any, new_id: str, old_owner: str) -> None:
    """Keep old Arena account on new tab (profile-correct)."""
    if not old_owner:
        return
    try:
        page = pool.get_page(new_id)
        if page is not None:
            page.owner = old_owner
        book = getattr(pool, "_alias", None)
        if book is not None:
            with pool._lock:
                ent = book._entries.get(new_id)
                if ent is not None:
                    ent["email"] = old_owner
    except Exception:
        pass
