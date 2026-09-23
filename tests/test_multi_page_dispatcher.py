"""Tests for allowed-tab gating in app/services/multi_page_dispatcher.py.

Bug 2026-09-18: parallel dispatch must only acquire tabs owned by checked
(enabled) URL rows. RULE 8: real PagePool/PageInfo, no Qt, no network.
"""

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import multi_page_dispatcher as mpd

pytestmark = pytest.mark.unit


def make_page(tab_id, jobs=0):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url="https://arena.ai", status=PageStatus.STEADY,
                    is_connected=True, jobs_completed=jobs)


def pool_with(*pages):
    pool = PagePool()
    for p in pages:
        pool.add_page(p)
    return pool


def test_acquire_free_in_takes_only_allowed_in_pool_order():
    """2026-09-21: the first free checked page takes the job — counts are display only."""
    pool = pool_with(make_page("free1", jobs=4), make_page("free2", jobs=1),
                     make_page("checked", jobs=9))
    got = mpd._acquire_free_in(pool, {"checked", "free2"}, "job1")
    assert got is not None and got.tab_id == "free2"  # first allowed in pool order
    assert got.status == PageStatus.BUSY and got.current_job_id == "job1"
    assert pool.get_page("free1").status == PageStatus.STEADY  # not checked: untouched
    assert pool.get_page("checked").status == PageStatus.STEADY


def test_acquire_free_in_only_ever_touches_the_checked_set():
    pool = pool_with(make_page("free1", jobs=4), make_page("checked", jobs=9))
    got = mpd._acquire_free_in(pool, {"checked"}, "job1")
    assert got is not None and got.tab_id == "checked"
    assert pool.get_page("free1").status == PageStatus.STEADY


def test_acquire_free_in_none_when_only_foreign_free():
    pool = pool_with(make_page("free1"), make_page("checked"))
    pool.mark_busy("checked", "other")
    assert mpd._acquire_free_in(pool, {"checked"}, "job1") is None


def test_acquire_free_in_tolerates_empty_and_garbage():
    pool = pool_with(make_page("a"))
    assert mpd._acquire_free_in(pool, set(), "job1") is None
    assert mpd._acquire_free_in(None, {"a"}, "job1") is None


def wait_spec(pool, allowed="checked", timeout=2.0, cancel=None):
    return mpd.FreeWaitSpec(pool=pool, allowed={allowed}, job_id="job1",
                            timeout_sec=timeout, cancel_check=cancel)


@pytest.mark.asyncio
async def test_wait_free_in_returns_page_when_allowed_frees():
    pool = pool_with(make_page("checked"))
    pool.mark_busy("checked", "other")

    async def freer():
        import asyncio
        await asyncio.sleep(0.05)
        pool.mark_steady("checked")

    import asyncio
    task = asyncio.create_task(freer())
    got = await mpd._wait_free_in(wait_spec(pool, cancel=lambda: False))
    await task
    assert got is not None and got.tab_id == "checked"


@pytest.mark.asyncio
async def test_wait_free_in_honours_cancel_and_timeout():
    pool = pool_with(make_page("checked"))
    pool.mark_busy("checked", "other")
    got = await mpd._wait_free_in(wait_spec(pool, timeout=5.0, cancel=lambda: True))
    assert got is None  # cancel breaks immediately
    got = await mpd._wait_free_in(wait_spec(pool, timeout=0.05, cancel=lambda: False))
    assert got is None  # bounded timeout, no infinite wait


@pytest.mark.asyncio
async def test_prepare_image_assigns_owning_row_without_foreign_relink():
    from types import SimpleNamespace
    from app.core.models import ImageItem, UrlRow

    foreign = UrlRow.create("https://arena.ai/x", enabled=True, tab_id="t9")
    owner = UrlRow.create("https://arena.ai/y", enabled=True, tab_id="t1")
    bridge = SimpleNamespace(state=SimpleNamespace(prompt={"user_prompt": "go"}))
    img = ImageItem.from_scan_dict({
        "id": "i1", "relative_path": "a.png", "absolute_path": "/tmp/a.png",
        "filename": "a.png", "base_name": "a", "extension": ".png", "size": 1,
        "mtime": 0.0, "fingerprint": "fp1"})
    url_row, corr, job_id, final = await mpd.prepare_image_for_job(
        bridge, img, [foreign, owner], "t1")
    assert url_row is owner  # the tab's own row is used…
    assert foreign.tab_id == "t9" and owner.tab_id == "t1"  # …no foreign relink
    assert img.assigned_url_id == owner.id
    assert corr and corr == job_id and "go" in final


@pytest.mark.asyncio
async def test_acquire_page_returns_free_checked_page():
    from types import SimpleNamespace
    pool = pool_with(make_page("checked"), make_page("foreign"))
    bridge = SimpleNamespace(_cancel_requested=False)
    got = await mpd._acquire_page(pool, bridge, "job1", {"checked"})
    assert got is not None and got.tab_id == "checked"
    assert pool.get_page("foreign").status == PageStatus.STEADY


class _LogBridge:
    """Minimal log/emit recorder (RULE 8: no Qt)."""

    def __init__(self, pool=None):
        self.logs = []
        self.emitted = 0
        self._page_pool = pool

    def _log(self, msg, level="info"):
        self.logs.append((level, msg))

    def _emit_pool_status(self):
        self.emitted += 1


def test_mark_steady_emit_logs_the_readable_label():
    """A silent NameError never eats the ✅ line again (2026-09-22, pyflakes lane:
    `tab_label_of` was used unimported and the helper's try/except swallowed it)."""
    pool = pool_with(make_page("tab-abcdef123456"))
    bridge = _LogBridge(pool)
    mpd._mark_steady_emit(pool, bridge, "tab-abcdef123456")
    assert bridge.emitted == 1
    assert any(lvl == "success" and "STEADY ready" in msg for lvl, msg in bridge.logs)


def test_log_no_ctrl_names_the_tab():
    pool = pool_with(make_page("tab-abcdef123456"))
    bridge = _LogBridge(pool)
    mpd._log_no_ctrl(bridge, "tab-abcdef123456")
    assert any(lvl == "warn" and "No controller" in msg for lvl, msg in bridge.logs)
    bridge2 = _LogBridge(None)                 # no pool: short id, still a line
    mpd._log_no_ctrl(bridge2, "tab-abcdef123456")
    assert any("No controller" in msg for _lvl, msg in bridge2.logs)
