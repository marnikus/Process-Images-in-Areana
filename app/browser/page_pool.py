"""PagePool — steady/busy tracking with RLock, event-driven wait (Phase 1+2)."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

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


def _pick_lowest_count(pages) -> Optional[PageInfo]:
    """Free page with fewest completed jobs; ties keep default order."""
    free = [p for p in pages if p.is_free()]
    if not free:
        return None
    return min(free, key=lambda p: p.jobs_completed)


def _snapshot_entry(page) -> dict:
    """One page snapshot entry incl. live cooldown countdown."""
    entry = page.to_dict()
    try:
        entry["cooldown_remaining"] = page.remaining_seconds()
    except Exception:
        entry["cooldown_remaining"] = 0
    return entry


class PagePool:
    def __init__(self, logger=None):
        self._pages: Dict[str, PageInfo] = {}
        self._aborts: set = set()
        self._clients: Dict[str, CDPClient] = {}
        self._controllers: Dict[str, CDPArenaController] = {}
        self._lock = threading.RLock()
        self._logger = logger or (lambda m, l="info": log.info(m))
        self._host = "127.0.0.1"
        self._port = 9222

    def add_page(self, info: PageInfo):
        tid = info.tab_id or info.ws_url
        if not tid:
            return
        with self._lock:
            exist = self._pages.get(tid)
            if exist:
                exist.title = info.title or exist.title
                exist.url = info.url or exist.url
                exist.ws_url = info.ws_url or exist.ws_url
                exist.is_connected = True
                if exist.status == PageStatus.DISCONNECTED:
                    exist.status = PageStatus.STEADY
                    exist.last_steady_at = now_iso()
            else:
                info.status = PageStatus.STEADY
                info.is_connected = True
                info.last_steady_at = now_iso()
                self._pages[tid] = info
        try:
            self._logger(f"Pool add {tid[:12]} steady", "success")
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
            return _pick_lowest_count(self._pages.values())

    async def acquire_free_page(self, job_id: str) -> Optional[PageInfo]:
        with self._lock:
            for p in self._pages.values():
                p.try_expire()
            page = _pick_lowest_count(self._pages.values())
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
            pages = [_snapshot_entry(p) for p in self._pages.values()]
            steady = len([p for p in self._pages.values() if p.is_free()])
            busy = len([p for p in self._pages.values() if p.is_busy()])
            cooling = len([p for p in self._pages.values() if p.status == PageStatus.COOLDOWN])
            return {"total": len(pages), "steady": steady, "busy": busy,
                    "cooling": cooling, "free": steady, "pages": pages}

    def register_client(self, tab_id: str, client: CDPClient, controller: CDPArenaController):
        with self._lock:
            self._clients[tab_id] = client
            self._controllers[tab_id] = controller

    def get_clients(self, tab_id: str):
        with self._lock:
            return self._clients.get(tab_id), self._controllers.get(tab_id)
