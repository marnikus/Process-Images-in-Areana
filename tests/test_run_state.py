"""Scheduling seam tests (A3): bg loop, schedule, tab/pool/restore helpers."""

import asyncio
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import run_state as rs


def make_bridge(pool=None, tmpdir=None):
    logs = []
    return SimpleNamespace(
        _page_pool=pool,
        _bg_loop=None, _bg_thread=None, _bg_lock=None, _bg_ready=None,
        _batch_future=None,
        _persist_ok=True,
        _restore_note_done=False,
        cdp=None,
        config=SimpleNamespace(dir=str(tmpdir) if tmpdir else "cfg",
                               get_state=lambda k, d=None: d),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("pool", "")),
        _logs=logs,
    )


def test_ensure_bg_loop_reuses_running():
    bridge = make_bridge()
    loop = rs.ensure_bg_loop(bridge)
    assert loop is not None and loop.is_running()
    assert rs.ensure_bg_loop(bridge) is loop


def test_schedule_coro_runs_and_tracks_batch():
    bridge = make_bridge()
    done = threading.Event()

    async def work():
        done.set()

    fut = rs.schedule_coro(bridge, work())
    assert fut is not None
    assert done.wait(timeout=5)

    async def run_batch():
        return None

    # S4: tracking is deliberate (schedule_batch), never by coroutine name
    fut_named = rs.schedule_coro(bridge, run_batch())
    fut_named.result(timeout=5)
    assert getattr(bridge, "_batch_future", None) is not fut_named

    async def any_name():
        return None

    fut2 = rs.schedule_batch(bridge, any_name())
    assert bridge._batch_future is fut2
    fut2.result(timeout=5)
    deadline = time.time() + 5
    while bridge._batch_future is not None and time.time() < deadline:
        time.sleep(0.01)
    assert bridge._batch_future is None


def test_batch_active_follows_the_future_not_the_label():
    """I-45: alive future → active (whatever _run_state says); done/cancelled/None → not."""
    bridge = make_bridge()
    assert rs.batch_active(bridge) is False
    fut = Future()
    bridge._batch_future = fut
    assert rs.batch_active(bridge) is True
    fut.set_result(None)
    assert rs.batch_active(bridge) is False
    cancelled = Future()
    cancelled.cancel()
    bridge._batch_future = cancelled
    assert rs.batch_active(bridge) is False
    assert rs.batch_active(SimpleNamespace()) is False  # attribute missing → not active


def test_on_coro_done_logs_errors_not_cancels():
    import concurrent.futures
    bridge = make_bridge()
    bad = Future()
    bad.set_exception(RuntimeError("boom"))
    rs._on_coro_done(bridge, bad)
    assert any("Async task failed" in m for m, _ in bridge._logs)
    cancelled = concurrent.futures.Future()
    cancelled.cancel()
    bridge._logs.clear()
    rs._on_coro_done(bridge, cancelled)
    assert bridge._logs == []


def test_schedule_detached_fallback(monkeypatch):
    monkeypatch.setattr(rs, "ensure_bg_loop", lambda bridge: None)
    bridge = make_bridge()
    done = threading.Event()

    async def work():
        done.set()

    assert rs.schedule_coro(bridge, work()) is None
    assert done.wait(timeout=5)


def test_schedule_failure_closes_coro(monkeypatch):
    monkeypatch.setattr(rs, "ensure_bg_loop", lambda bridge: (_ for _ in ()).throw(RuntimeError("x")))

    async def work():
        pass

    assert rs.schedule_coro(make_bridge(), work()) is None


def _cdp(title="", url="", tabs=None, fail=False):
    async def fetch():
        if fail:
            raise RuntimeError("down")
        return tabs or []

    return SimpleNamespace(_current_title=title, _current_url=url,
                           _current_ws_url="ws://t", fetch_tabs=fetch)


@pytest.mark.asyncio
async def test_resolve_tab_info_paths():
    tabs = [SimpleNamespace(id="t1", ws_url="ws://a", title="TA", url="https://a"),
            SimpleNamespace(id="t2", ws_url="ws://b", title="TB", url="https://b")]
    bridge = make_bridge()
    bridge.cdp = _cdp("CT", "CU", tabs)
    assert await rs.resolve_tab_info(bridge, "t2", "") == ("TB", "https://b")
    assert await rs.resolve_tab_info(bridge, "", "ws://a") == ("TA", "https://a")
    assert await rs.resolve_tab_info(bridge, "zz", "") == ("CT", "CU")
    bridge.cdp = _cdp("CT", "CU", fail=True)
    assert await rs.resolve_tab_info(bridge, "t1", "") == ("CT", "CU")
    assert rs._tab_attr(SimpleNamespace(), "id") == ""


@pytest.mark.asyncio
async def test_ensure_pool_page_paths(tmp_path):
    bridge = make_bridge(pool=None, tmpdir=tmp_path)
    await rs.ensure_pool_page(bridge, "t1")  # no pool -> silent
    assert bridge._logs == []

    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://t", title="T", url="https://arena.ai/x"))
    bridge = make_bridge(pool=pool, tmpdir=tmp_path)
    bridge.cdp = _cdp()
    await rs.ensure_pool_page(bridge, "t1")  # complete page -> no-op
    assert pool.get_page("t1").title == "T"

    bridge.cdp = _cdp("Live", "https://arena.ai/live",
                      [SimpleNamespace(id="t9", ws_url="ws://t9", title="LT", url="https://arena.ai/live")])
    await rs.ensure_pool_page(bridge, "t9")  # missing page -> registered
    assert pool.get_page("t9") is not None
    assert ("pool", "") in bridge._logs


def test_cooldowns_path_and_persist(tmp_path):
    bridge = make_bridge(tmpdir=tmp_path)
    assert rs.cooldowns_path(bridge).endswith("cooldowns.json")
    assert rs.cooldowns_path(SimpleNamespace(config=SimpleNamespace())) == "config/cooldowns.json"
    rs.persist_cooldowns(bridge)  # no pool -> silent
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://t", title="T", url="https://arena.ai/x"))
    bridge._page_pool = pool
    rs.persist_cooldowns(bridge)
    assert (tmp_path / "cooldowns.json").exists()
    assert rs.pooled_ids(pool) == {"t1"}
    assert rs.pooled_ids(None) == set()


def test_restore_page_state_no_file_and_miss(tmp_path):
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://t", title="T", url="https://arena.ai/x"))
    bridge = make_bridge(pool=pool, tmpdir=tmp_path)
    rs.restore_page_state(bridge, "t1")
    assert any("No saved timers" in m for m, _ in bridge._logs)
    rs.restore_page_state(make_bridge(pool=None), "t1")  # silent


def test_restore_page_state_applies_live_entry(tmp_path):
    import time as _t
    from app.persistence.cooldown_store import save_entries
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://t", title="T", url="https://arena.ai/x"))
    bridge = make_bridge(pool=pool, tmpdir=tmp_path)
    save_entries(str(tmp_path / "cooldowns.json"), {
        "t1": {"tab_id": "t1", "url": "https://arena.ai/x", "title": "T",
               "cooldown_until": _t.time() + 600, "cooldown_total": 600,
               "pending_penalty": 0, "captcha_count": 0, "reason": "job",
               "saved_at": _t.time()}})
    rs.restore_page_state(bridge, "t1")
    assert pool.get_page("t1").status == PageStatus.COOLDOWN
    assert any("Restored cooldown" in m for m, _ in bridge._logs)


def test_restore_page_state_miss_for_other_tab(tmp_path):
    import time as _t
    from app.persistence.cooldown_store import save_entries
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://t", title="T", url="https://arena.ai/x"))
    bridge = make_bridge(pool=pool, tmpdir=tmp_path)
    save_entries(str(tmp_path / "cooldowns.json"), {
        "zz": {"tab_id": "zz", "url": "https://arena.ai/other", "title": "O",
               "cooldown_until": _t.time() + 600, "cooldown_total": 600,
               "pending_penalty": 0, "captcha_count": 0, "reason": "job",
               "saved_at": _t.time()}})
    rs.restore_page_state(bridge, "t1")
    assert any("restore missed" in m for m, _ in bridge._logs)
