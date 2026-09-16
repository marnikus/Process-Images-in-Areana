"""Auto-connect linking — turn one detection pass into pool connections (spec 03).

Single responsibility: given the pages that matched, link the new ones, keep the
already-linked ones, and drop the ones that disappeared or stopped matching.
Scheduling lives in :mod:`app.browser.autoconnect_service`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

log = logging.getLogger("arena")

Connecter = Callable[[Dict[str, Any]], Awaitable[bool]]
Disconnector = Callable[[str], Any]
Logger = Callable[[str, str], None]


def _noop_log(_msg: str, _level: str = "info") -> None:
    return None


def _read_pool_ids(pool: Any) -> set:
    """Page ids currently in the pool — unique id, never the URL."""
    try:
        if not pool:
            return set()
        getter = getattr(pool, "page_ids", None)
        if callable(getter):
            return set(getter() or ())
        snap = pool.status_snapshot()
        return {p.get("tab_id") for p in snap.get("pages", []) if p.get("tab_id")}
    except Exception as e:
        log.debug(f"auto-connect pool read failed: {e}")
        return set()


@dataclass
class LinkOutcome:
    """What one pass did — ids, so the report can be read without the pool."""

    linked: List[str] = field(default_factory=list)
    adopted: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)

    def record(self, page_id: str, verdict: str) -> None:
        bucket = getattr(self, verdict, None)
        if bucket is not None:
            bucket.append(page_id)


class PageLinker:
    """Links matching pages into the pool, keyed by unique CDP page id."""

    def __init__(
        self,
        pool: Any = None,
        connect_page: Optional[Connecter] = None,
        disconnect_page: Optional[Disconnector] = None,
        logger: Optional[Logger] = None,
    ):
        self._pool = pool
        self._connect_page = connect_page
        self._disconnect_page = disconnect_page
        self._log = logger or _noop_log
        self._auto_ids: set = set()
        self._inflight: set = set()
        self._scans = 0
        self._last_scan_at = 0.0

    def known_ids(self) -> set:
        return _read_pool_ids(self._pool)

    async def reconcile(self, selection, reason: str = "scan") -> Dict[str, Any]:
        """Link wanted pages, drop unwanted ones, return the report dict."""
        self._scans += 1
        self._last_scan_at = time.time()
        known = self.known_ids()
        outcome = await self._link_all(selection.pages, known)
        outcome.removed = self._reap(selection, known)
        return self._report(selection, reason, outcome)

    async def _link_all(self, pages: List[Dict[str, Any]], known: set) -> LinkOutcome:
        outcome = LinkOutcome()
        for page in pages:
            outcome.record(page.get("page_id", ""), await self.link_one(page, known))
        return outcome

    async def link_one(self, page: Dict[str, Any], known: Optional[set] = None) -> str:
        """Link one page: ``linked`` / ``adopted`` (already pooled) / ``failed``.

        Already-pooled pages are adopted, never re-dialled — a re-scan must not
        churn websockets for a connection that is still alive.
        """
        pid = page.get("page_id") or ""
        if not pid:
            return "skipped"
        if pid in self._inflight:
            return "adopted"
        known = self.known_ids() if known is None else known
        if pid in known:
            self._auto_ids.add(pid)
            return "adopted"
        return "linked" if await self._dial(page, pid) else "failed"

    async def _dial(self, page: Dict[str, Any], pid: str, offload: bool = True) -> bool:
        """Connect one page. The blocking handshake runs in a worker thread so a
        dead tab can never stall the event loop (and with it the UI + timer)."""
        if not self._connect_page:
            return False
        self._inflight.add(pid)
        try:
            ok = bool(await self._handshake(page, offload))
        except Exception as e:
            ok = False
            self._log(f"❌ Auto-connect error for page {pid[:12]} ({page.get('url','')[:60]}): {e}", "error")
        finally:
            self._inflight.discard(pid)
        self._announce(page, pid, ok)
        if ok:
            self._auto_ids.add(pid)
        return ok

    async def _handshake(self, page: Dict[str, Any], offload: bool) -> bool:
        if not offload:
            return await self._connect_page(page)
        return await asyncio.to_thread(self._handshake_sync, page)

    def _handshake_sync(self, page: Dict[str, Any]) -> bool:
        return asyncio.run(self._connect_page(page))

    def _announce(self, page: Dict[str, Any], pid: str, ok: bool) -> None:
        if ok:
            label = page.get("title") or page.get("url") or pid
            self._log(f"🔗 Auto-connected page {pid[:12]} — {str(label)[:60]}", "success")
        else:
            self._log(f"❌ Auto-connect refused for page {pid[:12]} — {page.get('url','')[:60]}", "error")

    def _reap(self, selection, known: set) -> List[str]:
        """Drop auto-added pages that closed or stopped matching (never busy ones)."""
        if not self._disconnect_page:
            return []
        wanted = {p.get("page_id") for p in selection.pages}
        return [pid for pid in sorted(known - wanted) if self._drop_if_idle(pid)]

    def _drop_if_idle(self, pid: str) -> bool:
        """Remove one stale page; a busy job or a manual page is never touched."""
        if pid not in self._auto_ids or self._is_busy(pid):
            return False
        try:
            self._disconnect_page(pid)
        except Exception as e:
            self._log(f"Auto-disconnect failed for {pid[:12]}: {e}", "warn")
            return False
        self._auto_ids.discard(pid)
        self._log(f"🔌 Page {pid[:12]} closed or no longer matches — removed from pool", "warn")
        return True

    def _is_busy(self, pid: str) -> bool:
        try:
            page = self._pool.get_page(pid) if self._pool else None
            return bool(page and page.is_busy())
        except Exception:
            return False

    def _report(self, selection, reason: str, outcome: LinkOutcome) -> Dict[str, Any]:
        data = selection.to_dict()
        data.pop("pages", None)
        data.update(
            {
                "reason": reason,
                "ok": not selection.error,
                "connected_now": len(outcome.linked),
                "connected_ids": outcome.linked,
                "already_linked": outcome.adopted,
                "failed": outcome.failed,
                "removed": outcome.removed,
                "pool_total": len(self.known_ids()),
                "auto_ids": sorted(self._auto_ids),
                "scans": self._scans,
                "last_scan_at": self._last_scan_at,
            }
        )
        return data
