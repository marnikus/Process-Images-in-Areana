"""The page gate — which pooled page may take a job right now (I-33, I-68).

A page qualifies only when it is free (steady, connected, no live timer) AND
its URL row is checked at the moment of the claim: `FreeWaitSpec.allowed_now`
is called on every attempt, so an uncheck mid-wait is honoured by the very
next one. Split from `multi_page_dispatcher` (RULE 18.2): the feeder decides
WHEN to claim, this decides WHICH page. Imports nothing from services.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable


def acquire_free_in(pool, allowed: set, job_id: str):
    """Lock-guarded acquire of a free page inside the checked-tab set (I-33).

    External-lock pattern (same as sync_pool_presence): PagePool keeps its
    15-method cap, this module keeps the gating decision. The first free checked
    page in pool order takes the job — the job counter is display only
    (2026-09-21: the I-28 load-balancing concept is gone)."""
    try:
        with pool._lock:
            for p in pool._pages.values():
                p.try_expire()
            free = [p for p in pool._pages.values()
                    if p.is_free() and p.tab_id in (allowed or set())]
            if not free:
                return None
            page = free[0]
    except AttributeError:
        return None
    pool.mark_busy(page.tab_id, job_id)
    return page


@dataclass
class FreeWaitSpec:
    """Wait inputs for one checked free page (keeps params ≤4, RULE 16)."""

    pool: object
    allowed_now: Callable[[], set]  # the checked-tab set, re-read on EVERY attempt (I-68)
    job_id: str
    timeout_sec: float
    cancel_check: object = None
    wake_wait: object = asyncio.sleep  # async (seconds) -> None; the bus wait, so a freed page is taken at once (B-2)
    poll_sec: float = 0.5  # the fallback poll between wakes


def _gave_up(spec: FreeWaitSpec, waited_sec: float) -> bool:
    """Cancel asked, or the bounded wait ran out (RULE 7)."""
    return bool(spec.cancel_check and spec.cancel_check()) or waited_sec > spec.timeout_sec


async def wait_free_in(spec: FreeWaitSpec):
    """Wait for a checked free page; the bus wake is the path, the poll the fallback."""
    loop = asyncio.get_event_loop()
    start = loop.time()
    while not _gave_up(spec, loop.time() - start):
        got = acquire_free_in(spec.pool, spec.allowed_now(), spec.job_id)
        if got:
            return got
        await spec.wake_wait(spec.poll_sec)
    return None
