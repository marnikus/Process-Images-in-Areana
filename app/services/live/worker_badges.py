"""Push the worker-id badge into pooled tabs (D-5).

Owns: *when* a badge is asserted or cleared — on a pool join, on every
reconciler pass (a navigation wipes injected DOM; New Chat navigates after
each job) and on removal. The JS itself lives in `browser.worker_badge`, and
the badge prints the page's readable id (`PageInfo.alias`, fallback: the pool
key) so a Chrome tab and its app row match by eye (D-5).

Per-page failures (tab closed mid-call, CDP hiccup) are swallowed: a badge is
cosmetic and must never break a join or a pass. Imports downward only
(`browser.worker_badge`, `browser.page_pool` shape via duck typing).
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Tuple

from app.browser.worker_badge import (
    WorkerBadgeSpec,
    build_worker_badge_clear_js,
    build_worker_badge_js,
)

log = logging.getLogger(__name__)


async def assert_badges(pool: Any) -> int:
    """Show `#n + id` in every connected page that has a client; returns how many were shown."""
    shown = 0
    for tab_id, page, client in connected_clients(pool):
        spec = WorkerBadgeSpec(worker_no=int(page.worker_no or 0),
                               tab_id=getattr(page, "alias", "") or tab_id)
        if await _evaluate_quietly(client, build_worker_badge_js(spec), tab_id):
            shown += 1
    return shown


async def clear_badge(client: Any, tab_id: str) -> bool:
    """Remove the badge through an already-resolved client (the caller captures it
    *before* `remove_page` drops it); False when absent or the call failed."""
    if client is None:
        return False
    return await _evaluate_quietly(client, build_worker_badge_clear_js(), tab_id)


def connected_clients(pool: Any) -> Iterable[Tuple[str, Any, Any]]:
    pages = dict(getattr(pool, "_pages", None) or {})
    for tab_id, page in pages.items():
        client = client_of(pool, tab_id)
        if client is not None and getattr(page, "is_connected", False):
            yield tab_id, page, client


def client_of(pool: Any, tab_id: str):
    try:
        return pool.get_clients(tab_id)[0]
    except Exception:
        return None


async def _evaluate_quietly(client: Any, js: str, tab_id: str) -> bool:
    try:
        await client.evaluate(js)
        return True
    except Exception as exc:  # cosmetic: never let a badge break a join or a pass
        log.debug("worker badge skipped for %s: %s", tab_id[:12], exc)
        return False
