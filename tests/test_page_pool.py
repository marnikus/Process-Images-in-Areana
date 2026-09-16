"""Tests for PagePool multi-page steady/busy tracking."""

import asyncio
import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus


def make_info(tab_id, title="T"):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=title, url="https://arena.ai", status=PageStatus.STEADY, is_connected=True)


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
    # busy page not free
    p = pool.get_page("a")
    assert p.is_busy()
    assert not p.is_free()
    # steady page free
    p2 = pool.get_page("b")
    assert p2.is_free()
    # mark steady restores free
    pool.mark_steady("a")
    total, free = pool.get_counts()
    assert free == 2


def test_remove_page():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    assert pool.remove_page("a") is True
    assert pool.get_counts()[0] == 1
    assert pool.remove_page("nonexistent") is False


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


@pytest.mark.asyncio
async def test_wait_for_free_page_respects_cancel():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "j1")
    # cancel immediately
    cancelled = False

    def cancel_check():
        return True

    res = await pool.wait_for_free_page(timeout_sec=1, cancel_check=cancel_check)
    assert res is None


@pytest.mark.asyncio
async def test_wait_for_free_page_timeout():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "j1")
    res = await pool.wait_for_free_page(timeout_sec=0.2, cancel_check=lambda: False)
    assert res is None


@pytest.mark.asyncio
async def test_wait_for_free_page_success_after_steady():
    pool = PagePool()
    pool.add_page(make_info("a"))

    async def make_steady():
        await asyncio.sleep(0.1)
        pool.mark_steady("a")

    pool.mark_busy("a", "j1")
    task = asyncio.create_task(make_steady())
    res = await pool.wait_for_free_page(timeout_sec=1, cancel_check=lambda: False)
    await task
    assert res is not None
    assert res.tab_id == "a"


def test_status_snapshot_pages():
    pool = PagePool()
    pool.add_page(make_info("a", title="Arena A"))
    pool.add_page(make_info("b", title="Arena B"))
    snap = pool.status_snapshot()
    assert len(snap["pages"]) == 2
    titles = [p["title"] for p in snap["pages"]]
    assert "Arena A" in titles


def test_no_double_send_to_busy():
    """Ensure free count decreases after busy, preventing double-send."""
    pool = PagePool()
    for i in range(3):
        pool.add_page(make_info(f"tab{i}"))
    assert pool.get_counts() == (3, 3)
    # Simulate dispatch to different pages
    pool.mark_busy("tab0", "job0")
    assert pool.get_counts() == (3, 2)
    pool.mark_busy("tab1", "job1")
    assert pool.get_counts() == (3, 1)
    # Only tab2 free
    import asyncio as _asyncio

    async def _get():
        return await pool.get_free_page()

    free = _asyncio.run(_get())
    assert free.tab_id == "tab2"
    # After finishing, steady
    pool.mark_steady("tab0")
    assert pool.get_counts()[1] == 2
