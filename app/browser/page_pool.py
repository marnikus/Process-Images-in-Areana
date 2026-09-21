"""PagePool — steady/busy tracking with RLock, event-driven wait (Phase 1+2).

The pool key is the CDP tab id (identity, RULE 15); every page also carries the
display label the UIs print (`PageInfo.alias` = `{email}_{4 digits}`), numbered
once per tab from the injected `AliasBook` (D-5) so a re-join never burns a new
number and the number survives a restart (the book is persisted).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..core.tab_alias import AliasBook
from .cdp_arena import CDPArenaController
from .cdp_client import CDPClient
from .page_status import PageInfo, PageStatus, now_iso

log = logging.getLogger("arena")


@dataclass
class PageWaitOpts:
    poll_interval: float = 0.5
    notify_event: Optional[asyncio.Event] = None


async def _sleep_or_notify(opts: PageWaitOpts):
    if opts.notify_event is None:
        await asyncio.sleep(opts.poll_interval)
        return
    try:
        await asyncio.wait_for(opts.notify_event.wait(), timeout=opts.poll_interval)
        try:
            opts.notify_event.clear()
        except Exception:
            pass
    except asyncio.TimeoutError:
        pass


def _expire_all(pages) -> None:
    """Flip expired cooldowns to steady (call with lock held)."""
    for page in pages:
        try:
            page.try_expire()
        except Exception:
            continue


def _pick_free(pages) -> Optional[PageInfo]:
    """First free page in pool order (join order = the `#n` worker number).

    2026-09-21: the per-tab job counter is display-only — it never decides who
    works next (the load-balancing concept I-28 is gone), so this pick is the
    pool's own insertion order and nothing else.
    """
    for page in pages:
        if page.is_free():
            return page
    return None


def _snapshot_entry(tab_id: str, page) -> dict:
    """One page snapshot entry incl. live cooldown countdown.

    `tab_id` is the POOL KEY (`PageInfo.tab_id or ws_url`) — the same string
    the worker badge carries (I-55): the join path that parsed the socket and
    the path that cached the tab must never show two different ids for one
    worker, so the snapshot reports the key, never a fallback field.
    """
    entry = page.to_dict()
    entry["tab_id"] = tab_id
    try:
        entry["cooldown_remaining"] = page.remaining_seconds()
    except Exception:
        entry["cooldown_remaining"] = 0
    try:
        entry["tab_label"] = page.alias      # readable id for every view (D-5)
    except Exception:
        entry["tab_label"] = ""
    return entry


def tab_label_of(pool, tab_id: str) -> str:
    """Readable label of a tab from a pool that may be absent (D-7).

    One source for every log line and view that names a worker: the pool key
    stays the identity (RULE 15), the label is what a human reads. A page
    without a readable id, an unknown tab or a missing pool degrades to the
    short id — never to an empty string.
    """
    try:
        page = pool.get_page(tab_id)
        return page.label if page is not None else str(tab_id or "")[:12]
    except Exception:
        return str(tab_id or "")[:12]


def _assign_alias(page: PageInfo, tab_id: str, book: AliasBook) -> None:
    """Give a page its readable id once: number from the book, account remembered.

    Idempotent — a known page keeps the number it already carries (its persisted
    one), and the book's last known account seeds `owner` until the probe
    answers, so a restart never shows `aka_…` for a tab we have already seen.
    """
    if not page.alias_no:
        page.alias_no = book.no_for(tab_id)
    book.remember(tab_id, page.owner)
    if not page.owner:
        page.owner = book.owner_for(tab_id)


def _revive(exist: PageInfo, info: PageInfo) -> None:
    """A known tab re-joins: refresh identity, reconnect, keep its worker number."""
    exist.title = info.title or exist.title
    exist.url = info.url or exist.url
    exist.ws_url = info.ws_url or exist.ws_url
    exist.is_connected = True
    if exist.status == PageStatus.DISCONNECTED:
        exist.status = PageStatus.STEADY
        exist.last_steady_at = now_iso()


class PagePool:
    def __init__(self, logger=None, alias_book: Optional[AliasBook] = None):
        self._pages: Dict[str, PageInfo] = {}
        self._aborts: set = set()
        self._clients: Dict[str, CDPClient] = {}
        self._controllers: Dict[str, CDPArenaController] = {}
        self._lock = threading.RLock()
        self._logger = logger or (lambda m, l="info": log.info(m))
        self._host = "127.0.0.1"
        self._port = 9222
        self._next_worker_no = 0  # session-stable join counter, never reused (D-3)
        self._alias = alias_book if alias_book is not None else AliasBook()

    def add_page(self, info: PageInfo):
        tid = info.tab_id or info.ws_url
        if not tid:
            return
        with self._lock:
            exist = self._pages.get(tid)
            if exist:
                _revive(exist, info)
                _assign_alias(exist, tid, self._alias)
            else:
                info.status = PageStatus.STEADY
                info.is_connected = True
                info.last_steady_at = now_iso()
                self._next_worker_no += 1
                info.worker_no = self._next_worker_no
                _assign_alias(info, tid, self._alias)
                self._pages[tid] = info
        try:
            self._logger(f"Pool add {tab_label_of(self, tid)} steady", "success")
        except Exception:
            pass

    def remove_page(self, tab_id: str) -> bool:
        with self._lock:
            if tab_id not in self._pages:
                return False
            self._pages.pop(tab_id, None)
            self._clients.pop(tab_id, None)
            self._controllers.pop(tab_id, None)
            return True

    def get_page(self, tab_id: str) -> Optional[PageInfo]:
        with self._lock:
            return self._pages.get(tab_id)

    def get_counts(self) -> Tuple[int, int]:
        with self._lock:
            _expire_all(self._pages.values())
            return len(self._pages), len([p for p in self._pages.values() if p.is_free()])

    def mark_busy(self, tab_id: str, job_id: str) -> bool:
        with self._lock:
            p = self._pages.get(tab_id)
            if not p:
                return False
            p.status = PageStatus.BUSY
            p.current_job_id = job_id
            p.busy_since = now_iso()
            p.error = None
            return True

    def mark_steady(self, tab_id: str) -> bool:
        with self._lock:
            p = self._pages.get(tab_id)
            if not p:
                return False
            p.status = PageStatus.STEADY
            p.current_job_id = None
            p.busy_since = None
            p.last_steady_at = now_iso()
            p.error = None
            return True

    def mark_waiting(self, tab_id: str, kind: str) -> bool:
        with self._lock:
            p = self._pages.get(tab_id)
            if not p:
                return False
            p.status = PageStatus.WAITING_CAPTCHA if kind == "captcha" else PageStatus.WAITING_GENERATION
            return True

    def mark_error(self, tab_id: str, err: str) -> bool:
        with self._lock:
            p = self._pages.get(tab_id)
            if not p:
                return False
            p.status = PageStatus.ERROR
            p.error = err
            p.current_job_id = None
            return True

    async def get_free_page(self) -> Optional[PageInfo]:
        with self._lock:
            for p in self._pages.values():
                p.try_expire()
            return _pick_free(self._pages.values())

    async def acquire_free_page(self, job_id: str) -> Optional[PageInfo]:
        with self._lock:
            for p in self._pages.values():
                p.try_expire()
            page = _pick_free(self._pages.values())
            if page is None:
                return None
            page.status = PageStatus.BUSY
            page.current_job_id = job_id
            page.busy_since = now_iso()
            page.error = None
            return page

    async def wait_for_free_page(self, timeout_sec: float, cancel_check=None, job_id: str = None, wait_opts: PageWaitOpts | None = None) -> Optional[PageInfo]:
        opts = wait_opts or PageWaitOpts()
        start = asyncio.get_event_loop().time()
        while True:
            if cancel_check and cancel_check():
                return None
            got = await self.acquire_free_page(job_id) if job_id else await self.get_free_page()
            if got:
                return got
            if asyncio.get_event_loop().time() - start > timeout_sec:
                return None
            await _sleep_or_notify(opts)

    def status_snapshot(self) -> dict:
        with self._lock:
            pages = [_snapshot_entry(tid, p) for tid, p in self._pages.items()]
            steady = len([p for p in self._pages.values() if p.is_free()])
            busy = len([p for p in self._pages.values() if p.is_busy()])
            cooling = len([p for p in self._pages.values() if p.is_cooling()])
            return {"total": len(pages), "steady": steady, "busy": busy,
                    "cooling": cooling, "free": steady, "pages": pages}

    def register_client(self, tab_id: str, client: CDPClient, controller: CDPArenaController):
        with self._lock:
            self._clients[tab_id] = client
            self._controllers[tab_id] = controller

    def get_clients(self, tab_id: str):
        with self._lock:
            return self._clients.get(tab_id), self._controllers.get(tab_id)
