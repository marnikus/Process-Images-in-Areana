"""Tests for PagePool multi-page steady/busy tracking — optimized Phase 1."""

import asyncio
import pytest

from app.browser.page_pool import PagePool, PageWaitOpts
from app.browser.page_status import PageInfo, PageStatus


def make_info(tab_id, title="T"):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=title, url="https://arena.ai", status=PageStatus.STEADY, is_connected=True)


@pytest.mark.unit
def test_add_and_counts():
    pool = PagePool()
    assert pool.get_counts() == (0, 0)
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    total, free = pool.get_counts()
    assert total == 2
    assert free == 2
    snap = pool.status_snapshot()
    assert snap["total"] == 2
    assert snap["steady"] == 2
    assert snap["busy"] == 0


@pytest.mark.unit
def test_mark_busy_steady():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    ok = pool.mark_busy("a", "job1")
    assert ok
    total, free = pool.get_counts()
    assert total == 2
    assert free == 1
    snap = pool.status_snapshot()
    assert snap["busy"] == 1
    assert snap["steady"] == 1
    p = pool.get_page("a")
    assert p.is_busy()
    assert not p.is_free()
    p2 = pool.get_page("b")
    assert p2.is_free()
    pool.mark_steady("a")
    total, free = pool.get_counts()
    assert free == 2


@pytest.mark.unit
def test_remove_page():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    assert pool.remove_page("a") is True
    assert pool.get_counts()[0] == 1
    assert pool.remove_page("nonexistent") is False


@pytest.mark.unit
def test_mark_waiting_error():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_waiting("a", "captcha")
    p = pool.get_page("a")
    assert p.status == PageStatus.WAITING_CAPTCHA
    assert not p.is_free()
    pool.mark_error("a", "oops")
    assert p.status == PageStatus.ERROR
    pool.mark_steady("a")
    assert p.is_free()


@pytest.mark.unit
def test_register_and_get_clients():
    pool = PagePool()
    pool.add_page(make_info("a"))
    fake_client = object()
    fake_ctrl = object()
    pool.register_client("a", fake_client, fake_ctrl)
    c, ctrl = pool.get_clients("a")
    assert c is fake_client
    assert ctrl is fake_ctrl
    c2, ctrl2 = pool.get_clients("missing")
    assert c2 is None and ctrl2 is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_free_page():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    free = await pool.get_free_page()
    assert free is not None
    assert free.tab_id in ("a", "b")
    pool.mark_busy("a", "j1")
    pool.mark_busy("b", "j2")
    free2 = await pool.get_free_page()
    assert free2 is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_free_page_respects_cancel():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "j1")

    def cancel_check():
        return True

    res = await pool.wait_for_free_page(timeout_sec=0.2, cancel_check=cancel_check, wait_opts=PageWaitOpts(poll_interval=0.01))
    assert res is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_free_page_timeout():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "j1")
    res = await pool.wait_for_free_page(timeout_sec=0.05, cancel_check=lambda: False, wait_opts=PageWaitOpts(poll_interval=0.01))
    assert res is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_free_page_success_after_steady():
    pool = PagePool()
    pool.add_page(make_info("a"))
    notify = asyncio.Event()

    async def make_steady():
        await asyncio.sleep(0.02)
        pool.mark_steady("a")
        notify.set()

    pool.mark_busy("a", "j1")
    task = asyncio.create_task(make_steady())
    res = await pool.wait_for_free_page(
        timeout_sec=1, cancel_check=lambda: False, wait_opts=PageWaitOpts(poll_interval=0.01, notify_event=notify)
    )
    await task
    assert res is not None
    assert res.tab_id == "a"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_free_page_event_driven_fast():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "j1")
    notify = asyncio.Event()

    async def make_steady_fast():
        await asyncio.sleep(0)
        pool.mark_steady("a")
        notify.set()

    task = asyncio.create_task(make_steady_fast())
    res = await pool.wait_for_free_page(
        timeout_sec=0.5, cancel_check=lambda: False, wait_opts=PageWaitOpts(poll_interval=0.01, notify_event=notify)
    )
    await task
    assert res is not None
    assert res.tab_id == "a"


@pytest.mark.unit
def test_status_snapshot_pages():
    pool = PagePool()
    pool.add_page(make_info("a", title="Arena A"))
    pool.add_page(make_info("b", title="Arena B"))
    snap = pool.status_snapshot()
    assert len(snap["pages"]) == 2
    titles = [p["title"] for p in snap["pages"]]
    assert "Arena A" in titles


@pytest.mark.unit
def test_no_double_send_to_busy():
    pool = PagePool()
    for i in range(3):
        pool.add_page(make_info(f"tab{i}"))
    assert pool.get_counts() == (3, 3)
    pool.mark_busy("tab0", "job0")
    assert pool.get_counts() == (3, 2)
    pool.mark_busy("tab1", "job1")
    assert pool.get_counts() == (3, 1)
    import asyncio as _asyncio

    async def _get():
        return await pool.get_free_page()

    free = _asyncio.run(_get())
    assert free.tab_id == "tab2"
    pool.mark_steady("tab0")
    assert pool.get_counts()[1] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_free_page_uses_pool_order_not_job_count():
    """2026-09-21: the counter is display-only — the pick is the first free tab."""
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    pool.add_page(make_info("c"))
    pool.get_page("a").jobs_completed = 5
    pool.get_page("b").jobs_completed = 2
    pool.get_page("c").jobs_completed = 3
    pool.mark_busy("b", "other")
    got = await pool.get_free_page()
    assert got.tab_id == "a"  # first free in pool order, whatever the counts say


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_uses_pool_order_and_marks_busy():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    pool.get_page("a").jobs_completed = 4
    pool.get_page("b").jobs_completed = 1
    got = await pool.acquire_free_page("j1")
    assert got.tab_id == "a"  # pool order: the count no longer reorders the queue
    assert pool.get_page("a").status == PageStatus.BUSY
    assert pool.get_counts() == (2, 1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pick_ties_keep_default_order():
    pool = PagePool()
    pool.add_page(make_info("x"))
    pool.add_page(make_info("y"))
    got = await pool.acquire_free_page("j1")
    assert got.tab_id == "x"
    got2 = await pool.get_free_page()
    assert got2.tab_id == "y"


@pytest.mark.unit
def test_snapshot_reports_the_pool_key_as_the_tab_id():
    """I-55 / worker badge: one worker, one id string — the key, never a fallback field."""
    pool = PagePool()
    key = "ws://127.0.0.1:9222/devtools/page/1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    pool.add_page(PageInfo(ws_url=key, tab_id="", title="T"))
    pool._pages[key].tab_id = "stale-fallback"  # a later join path rewriting the field must not leak
    (entry,) = pool.status_snapshot()["pages"]
    assert entry["tab_id"] == key
