"""Resolve each pooled tab's logged-in account → its readable label (D-5).

Owns *when* the owner probe runs: on a pool join (the UI slot calls
`resolve_owners` right away, exactly like the worker badge) and on every
reconciler pass, because New Chat navigates and a tab can sign out or switch
accounts. Best-effort like the badge (RULE 15): a page without a client, a dead
socket or a nonsense reply leaves the email we already have, so a label never
regresses to `aka_…` and a probe hiccup can never break a join or a pass.

Imports downward only: `browser.owner_probe`, `core.tab_alias`, and the badge's
page enumeration (one home for "pooled pages that have a client").
"""

from __future__ import annotations

import logging
from typing import Any

from app.browser.owner_probe import build_owner_probe, interpret_owner
from app.core.tab_alias import normalize_owner
from app.services.live.worker_badges import client_of, connected_clients

log = logging.getLogger(__name__)


async def resolve_owners(pool: Any) -> int:
    """Probe every connected pooled page; returns how many accounts were read."""
    if pool is None:
        return 0
    found = 0
    for tab_id, page, client in connected_clients(pool):
        email = await _read_owner(client, tab_id)
        if not email:
            continue
        found += 1
        if email != getattr(page, "owner", ""):
            store_owner(pool, tab_id, page, email)
    return found


async def _read_owner(client: Any, tab_id: str) -> str:
    """One probe call → normalized email ('' when silent, broken or not an address)."""
    try:
        reply = await client.evaluate(build_owner_probe())
    except Exception as exc:  # cosmetic: never break a join or a pass
        log.debug("owner probe skipped for %s: %s", str(tab_id)[:12], exc)
        return ""
    return normalize_owner(interpret_owner(reply).get("email"))


def store_owner(pool: Any, tab_id: str, page: Any, email: str) -> None:
    """Write the account on the page and into the alias book (pool-locked).

    Shared with the Firefox identify drain (`firefox_identity`): one writer.
    """
    try:
        with pool._lock:
            page.owner = email
            book = getattr(pool, "_alias", None)
            if book is not None:
                book.remember(tab_id, email)
    except Exception:
        pass


__all__ = ["resolve_owners", "store_owner", "client_of"]
