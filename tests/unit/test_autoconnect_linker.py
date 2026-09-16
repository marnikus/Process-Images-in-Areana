"""Unit tests — PageLinker: link matched pages, drop the ones that went away (spec 03).

Uses the real PagePool (RULE 8) and a fake connect/disconnect pair.
"""

from __future__ import annotations

import pytest

from app.browser.autoconnect_linker import PageLinker
from app.browser.autoconnect_match import select_pages, compile_patterns
from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus

def pool_ids(pool) -> list:
    """Sorted page ids in the pool — the pool is the source of truth."""
    return sorted(p["tab_id"] for p in pool.status_snapshot()["pages"])


def page(pid: str, url: str = "https://arena.ai/c/1", title: str = "Arena") -> dict:
    return {"page_id": pid, "title": title, "url": url, "ws_url": f"ws://127.0.0.1:9223/devtools/page/{pid}"}


def tab(pid: str, url: str = "https://arena.ai/c/1", title: str = "Arena") -> dict:
    return {"id": pid, "title": title, "url": url, "ws_url": f"ws://127.0.0.1:9223/devtools/page/{pid}"}


class Recorder:
    """Fake connecter/disconnector that mirrors the pool like Bridge does."""

    def __init__(self, pool: PagePool, refuse: set | None = None, raise_on: set | None = None):
        self.pool = pool
        self.refuse = refuse or set()
        self.raise_on = raise_on or set()
        self.connected: list = []
        self.disconnected: list = []

    async def connect(self, pg: dict) -> bool:
        pid = pg["page_id"]
        self.connected.append(pid)
        if pid in self.raise_on:
            raise ConnectionError(f"websocket refused for {pid}")
        if pid in self.refuse:
            return False
        self.pool.add_page(PageInfo(tab_id=pid, ws_url=pg["ws_url"], title=pg["title"], url=pg["url"]))
        return True

    def disconnect(self, pid: str) -> bool:
        self.disconnected.append(pid)
        return self.pool.remove_page(pid)


def make_linker(pool=None, **kw):
    pool = pool or PagePool()
    rec = Recorder(pool, **kw)
    logs: list = []
    linker = PageLinker(pool=pool, connect_page=rec.connect, disconnect_page=rec.disconnect,
                        logger=lambda m, lvl="info": logs.append((m, lvl)))
    return linker, pool, rec, logs


def selection_of(tabs, pattern="arena.ai", max_pages=0):
    return select_pages(tabs, compile_patterns(pattern), max_pages)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_links_every_matching_page_including_same_url_twice():
    linker, pool, rec, _logs = make_linker()
    report = await linker.reconcile(selection_of([tab("AAA"), tab("BBB")]))
    assert report["connected_now"] == 2
    assert sorted(pool_ids(pool)) == ["AAA", "BBB"]
    assert rec.connected == ["AAA", "BBB"]
    assert report["pool_total"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_second_scan_does_not_redial_linked_pages():
    linker, pool, rec, _logs = make_linker()
    await linker.reconcile(selection_of([tab("AAA")]))
    await linker.reconcile(selection_of([tab("AAA")]))
    assert rec.connected == ["AAA"]  # exactly one dial, no reconnect churn
    assert pool.get_page("AAA").is_free()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_tab_on_next_scan_is_added_automatically():
    linker, pool, rec, _logs = make_linker()
    await linker.reconcile(selection_of([tab("AAA")]))
    report = await linker.reconcile(selection_of([tab("AAA"), tab("BBB")]))
    assert report["connected_now"] == 1
    assert sorted(pool_ids(pool)) == ["AAA", "BBB"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_closed_page_is_removed_from_pool():
    linker, pool, rec, logs = make_linker()
    await linker.reconcile(selection_of([tab("AAA"), tab("BBB")]))
    report = await linker.reconcile(selection_of([tab("AAA")]))
    assert report["removed"] == ["BBB"]
    assert pool_ids(pool) == ["AAA"]
    assert rec.disconnected == ["BBB"]
    assert any("no longer matches" in m for m, _l in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_page_that_stops_matching_pattern_is_removed():
    linker, pool, rec, _logs = make_linker()
    await linker.reconcile(selection_of([tab("AAA", url="https://arena.ai/c/1")]))
    # same page id, navigated away from the pattern
    report = await linker.reconcile(selection_of([tab("AAA", url="https://docs.python.org/")]))
    assert report["removed"] == ["AAA"]
    assert pool_ids(pool) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_busy_page_is_never_dropped():
    linker, pool, rec, _logs = make_linker()
    await linker.reconcile(selection_of([tab("AAA"), tab("BBB")]))
    pool.mark_busy("BBB", "job-1")
    report = await linker.reconcile(selection_of([tab("AAA")]))
    assert report["removed"] == []
    assert "BBB" in pool_ids(pool)
    assert pool.get_page("BBB").status == PageStatus.BUSY


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manually_added_page_is_not_removed_by_autoconnect():
    linker, pool, rec, _logs = make_linker()
    pool.add_page(PageInfo(tab_id="MANUAL", ws_url="ws://x/devtools/page/MANUAL", title="Other",
                           url="https://example.com/"))
    report = await linker.reconcile(selection_of([tab("AAA")]))
    assert report["removed"] == []
    assert "MANUAL" in pool_ids(pool)
    assert rec.disconnected == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refused_and_raising_connections_are_reported_not_silent():
    linker, pool, rec, logs = make_linker(refuse={"BBB"}, raise_on={"CCC"})
    report = await linker.reconcile(selection_of([tab("AAA"), tab("BBB"), tab("CCC")]))
    assert report["connected_now"] == 1
    assert sorted(report["failed"]) == ["BBB", "CCC"]
    assert pool_ids(pool) == ["AAA"]
    assert any(lvl == "error" and "refused" in m for m, lvl in logs)
    assert any(lvl == "error" and "error" in m for m, lvl in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_page_is_retried_on_next_scan():
    linker, pool, rec, _logs = make_linker(refuse={"AAA"})
    await linker.reconcile(selection_of([tab("AAA")]))
    assert pool_ids(pool) == []
    rec.refuse.clear()
    report = await linker.reconcile(selection_of([tab("AAA")]))
    assert report["connected_now"] == 1
    assert pool_ids(pool) == ["AAA"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scan_without_fetcher_reports_zero_pages_not_failure():
    pool = PagePool()
    logs: list = []
    linker = PageLinker(pool=pool, connect_page=None, disconnect_page=None,
                        logger=lambda m, lvl="info": logs.append((m, lvl)))
    report = await linker.reconcile(selection_of([]))
    assert report["connected_now"] == 0
    assert report["scanned"] == 0
    assert report["ok"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_report_carries_scan_counters_and_auto_ids():
    linker, _pool, _rec, _logs = make_linker()
    report = await linker.reconcile(selection_of([tab("AAA"), tab("BBB")], max_pages=1))
    assert report["scans"] == 1
    assert report["auto_ids"] == [report["connected_ids"][0]]
    assert report["limited"] is True
    assert report["matched"] == 2
    assert report["last_scan_at"] > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linker_works_without_pool_object():
    dialled: list = []

    async def connect(pg):
        dialled.append(pg["page_id"])
        return True

    linker = PageLinker(pool=None, connect_page=connect)
    report = await linker.reconcile(selection_of([tab("AAA")]))
    assert dialled == ["AAA"]
    assert report["pool_total"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_error_keeps_the_page_and_warns():
    pool = PagePool()
    logs: list = []

    async def connect(pg):
        pool.add_page(PageInfo(tab_id=pg["page_id"], ws_url=pg["ws_url"], title=pg["title"], url=pg["url"]))
        return True

    def boom(_pid):
        raise RuntimeError("pool locked")

    linker = PageLinker(pool=pool, connect_page=connect, disconnect_page=boom,
                        logger=lambda m, lvl="info": logs.append((m, lvl)))
    await linker.reconcile(selection_of([tab("AAA"), tab("BBB")]))
    report = await linker.reconcile(selection_of([tab("AAA")]))
    assert report["removed"] == []
    assert sorted(pool_ids(pool)) == ["AAA", "BBB"]
    assert any(lvl == "warn" and "Auto-disconnect failed" in m for m, lvl in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_page_without_id_is_skipped():
    linker, pool, rec, _logs = make_linker()
    report = await linker.reconcile(selection_of([tab("AAA")]))
    assert report["connected_now"] == 1
    outcome = await linker.link_one({"page_id": "", "url": "https://arena.ai/", "ws_url": ""})
    assert outcome == "skipped"
    assert pool_ids(pool) == ["AAA"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_link_of_same_page_dials_once():
    linker, pool, rec, _logs = make_linker()
    linker._inflight.add("AAA")  # a dial for this page is already running
    outcome = await linker.link_one(page("AAA"))
    assert outcome == "adopted"
    assert rec.connected == []
    assert pool_ids(pool) == []


@pytest.mark.unit
def test_link_outcome_records_only_known_buckets():
    from app.browser.autoconnect_linker import LinkOutcome

    outcome = LinkOutcome()
    outcome.record("A", "linked")
    outcome.record("B", "adopted")
    outcome.record("C", "failed")
    outcome.record("D", "skipped")  # no bucket — ignored, never invents state
    assert (outcome.linked, outcome.adopted, outcome.failed) == (["A"], ["B"], ["C"])
    assert outcome.removed == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dial_offloads_the_handshake_to_a_worker_thread():
    """A slow websocket handshake must not block the event loop (UI + timer)."""
    import asyncio
    import threading

    pool = PagePool()
    seen: list = []

    async def slow_connect(pg: dict) -> bool:
        seen.append(threading.current_thread() is threading.main_thread())
        await asyncio.sleep(0.05)
        pool.add_page(PageInfo(tab_id=pg["page_id"], ws_url=pg["ws_url"], url=pg["url"], is_connected=True))
        return True

    linker = PageLinker(pool=pool, connect_page=slow_connect, disconnect_page=pool.remove_page)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while ticks < 50:
            await asyncio.sleep(0.005)
            ticks += 1

    tick = asyncio.ensure_future(ticker())
    outcome = await linker.link_one(page("AAA"))
    await tick

    assert outcome == "linked"
    assert seen == [False]  # the handshake ran off the loop thread
    assert ticks == 50  # the loop kept breathing while it ran
    assert pool_ids(pool) == ["AAA"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handshake_error_in_the_worker_thread_is_reported_not_raised():
    linker, pool, _rec, logs = make_linker()

    async def boom(_pg: dict) -> bool:
        raise OSError("websocket handshake timed out")

    linker._connect_page = boom
    outcome = await linker.link_one(page("AAA"))

    assert outcome == "failed"
    assert pool_ids(pool) == []
    assert any(lvl == "error" and "handshake timed out" in m for m, lvl in logs)
