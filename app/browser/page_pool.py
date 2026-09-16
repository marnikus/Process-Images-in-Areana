"""PagePool — multi-page steady/busy tracking.

Fix for UI freeze: previously used asyncio.Lock created in main thread but used in
background asyncio loop thread — loop mismatch causes deadlock / freeze.
Now uses threading.RLock for all sync/async access, never blocks UI thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Dict, Optional, Tuple

from .cdp_arena import CDPArenaController
from .cdp_client import CDPClient
from .page_status import PageInfo, PageStatus, now_iso

log = logging.getLogger("arena")


class PagePool:
    def __init__(self, logger=None):
        self._pages: Dict[str, PageInfo] = {}
        self._clients: Dict[str, CDPClient] = {}
        self._controllers: Dict[str, CDPArenaController] = {}
        # Use threading lock — safe across Qt main thread and bg asyncio thread
        # Avoids asyncio.Lock loop mismatch that froze mouse clicks
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
            total = len(self._pages)
            free = len([p for p in self._pages.values() if p.is_free()])
            return total, free

    def mark_busy(self, tab_id: str, job_id: str) -> bool:
        with self._lock:
            page = self._pages.get(tab_id)
            if not page:
                return False
            page.status = PageStatus.BUSY
            page.current_job_id = job_id
            page.busy_since = now_iso()
            page.error = None
            return True

    def mark_steady(self, tab_id: str) -> bool:
        with self._lock:
            page = self._pages.get(tab_id)
            if not page:
                return False
            page.status = PageStatus.STEADY
            page.current_job_id = None
            page.busy_since = None
            page.last_steady_at = now_iso()
            page.error = None
            return True

    def mark_waiting(self, tab_id: str, kind: str) -> bool:
        with self._lock:
            page = self._pages.get(tab_id)
            if not page:
                return False
            page.status = PageStatus.WAITING_CAPTCHA if kind == "captcha" else PageStatus.WAITING_GENERATION
            return True

    def mark_error(self, tab_id: str, err: str) -> bool:
        with self._lock:
            page = self._pages.get(tab_id)
            if not page:
                return False
            page.status = PageStatus.ERROR
            page.error = err
            page.current_job_id = None
            return True

    async def get_free_page(self) -> Optional[PageInfo]:
        # Non-blocking quick check — uses threading lock, not asyncio lock
        with self._lock:
            for p in self._pages.values():
                if p.is_free():
                    return p
            return None

    async def acquire_free_page(self, job_id: str) -> Optional[PageInfo]:
        # Atomic acquire — thread-safe, no asyncio.Lock loop mismatch
        with self._lock:
            for p in self._pages.values():
                if p.is_free():
                    p.status = PageStatus.BUSY
                    p.current_job_id = job_id
                    p.busy_since = now_iso()
                    p.error = None
                    return p
            return None

    async def wait_for_free_page(self, timeout_sec: float, cancel_check=None, job_id: str = None) -> Optional[PageInfo]:
        start = asyncio.get_event_loop().time()
        while True:
            if cancel_check and cancel_check():
                return None
            if job_id:
                acquired = await self.acquire_free_page(job_id)
                if acquired:
                    return acquired
            else:
                free = await self.get_free_page()
                if free:
                    return free
            if asyncio.get_event_loop().time() - start > timeout_sec:
                return None
            await asyncio.sleep(0.5)

    def status_snapshot(self) -> dict:
        with self._lock:
            pages = [p.to_dict() for p in self._pages.values()]
            steady = len([p for p in self._pages.values() if p.is_free()])
            busy = len([p for p in self._pages.values() if p.is_busy()])
            return {"total": len(pages), "steady": steady, "busy": busy, "free": steady, "pages": pages}

    def register_client(self, tab_id: str, client: CDPClient, controller: CDPArenaController):
        with self._lock:
            self._clients[tab_id] = client
            self._controllers[tab_id] = controller

    def get_clients(self, tab_id: str):
        with self._lock:
            return self._clients.get(tab_id), self._controllers.get(tab_id)
