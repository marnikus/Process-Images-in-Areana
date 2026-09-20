"""Captcha boundary checks + row-tab binding (2026-09-17).

RULE 8: real PagePool + service; only CDP/bridge boundary faked.
Covers dispatcher submit/download boundary checks (F4) and the sticky
URL-row → tab link (F10) that keeps each row on its own tab's timer.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.models import UrlRow
from app.services import single_job_runner as sjr
from app.services.multi_page_dispatcher import PageJobCtx, _run_image_job


def make_info(tab_id):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                     url="https://arena.ai", status=PageStatus.STEADY, is_connected=True)


ON = {"watcher_enabled": True}  # S2: captcha work is in scope only while the Watcher is ON


def make_bridge(pool, session=None):
    state = {"cooldown_enabled": True, "cooldown_min_seconds": 300,
             "cooldown_captcha_penalty_seconds": 900}
    if session:
        state.update(session)
    logs = []
    return SimpleNamespace(
        _cancel_requested=False,
        _page_pool=pool,
        _ensure_page_pool=lambda: pool,
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        _logs=logs,
    )


def make_ctrl(visible_seq):
    seq = list(visible_seq)
    calls = []

    async def fake_visible():
        calls.append("visible")
        return seq.pop(0) if seq else False

    async def fake_overlay(*a, **k):
        calls.append("overlay")

    async def fake_hide(*a, **k):
        calls.append("hide")

    async def fake_submit():
        return True, "ok"

    async def fake_download(src):
        return True, b"y" * 200, "image/png"

    ctrl = SimpleNamespace(
        is_security_dialog_visible=fake_visible,
        show_watcher_overlay=fake_overlay,
        hide_watcher_overlay=fake_hide,
        submit=fake_submit,
        download_image=fake_download,
    )
    return ctrl, calls


def make_ctx(pool, bridge, ctrl, tab_id="t1"):
    img = SimpleNamespace(status="pending", error="", output_path="",
                          relative_path="pic.png")
    return sjr.JobCtx(bridge=bridge, ctrl=ctrl, client=None, tab_id=tab_id,
                      img=img, urls=[], job_id="j1", corr_id="c1",
                      final_prompt="p [JOB-ID: c1]")


def instant_sleep(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_security_noop_when_clear():
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, ON)
    ctrl, _ = make_ctrl([False])
    ctx = make_ctx(pool, bridge, ctrl)
    assert await sjr.check_security(ctx) is False
    assert pool.get_page("t1").pending_penalty == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_security_visible_records_penalty(monkeypatch):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.mark_busy("t1", "j1")
    bridge = make_bridge(pool, ON)
    ctrl, _ = make_ctrl([True, False])
    ctx = make_ctx(pool, bridge, ctrl)
    assert await sjr.check_security(ctx) is True
    assert pool.get_page("t1").pending_penalty == 900
    assert any("🛡️" in m for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_boundary_clear_no_penalty():
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.mark_busy("t1", "j1")
    bridge = make_bridge(pool, ON)
    ctrl, _ = make_ctrl([False])
    ctx = make_ctx(pool, bridge, ctrl)
    await sjr._handle_submit(ctx, SimpleNamespace())
    assert pool.get_page("t1").pending_penalty == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_boundary_visible_records(monkeypatch):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.mark_busy("t1", "j1")
    bridge = make_bridge(pool, ON)
    ctrl, _ = make_ctrl([True, False])
    ctx = make_ctx(pool, bridge, ctrl)
    await sjr._handle_submit(ctx, SimpleNamespace())
    assert pool.get_page("t1").pending_penalty == 900


@pytest.mark.unit
@pytest.mark.asyncio
async def test_download_boundary_visible_records(monkeypatch):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.mark_busy("t1", "j1")
    bridge = make_bridge(pool, ON)
    ctrl, _ = make_ctrl([True, False])
    ctx = make_ctx(pool, bridge, ctrl)
    ctx.new_src = "https://cdn/x.png"
    await sjr._handle_download(ctx, SimpleNamespace())
    assert pool.get_page("t1").pending_penalty == 900
    assert len(ctx.file_bytes) == 200


@pytest.mark.unit
def test_url_row_link_tab():
    row = UrlRow.create("https://arena.ai")
    assert row.tab_id == ""
    assert row.link_tab("tab9") is True
    assert row.tab_id == "tab9"
    assert row.link_tab("") is False
    assert row.tab_id == "tab9"  # empty never clears the link


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_records_owner_row_without_relinking():
    """I-33: dispatch records the tab's OWN checked row; ownership belongs
    to auto-connect, so runs never re-bind a row to a foreign tab."""
    pool = PagePool()
    pool.add_page(make_info("t9"))
    saved = []
    state = SimpleNamespace(prompt={"user_prompt": "p"},
                            recalculate_progress=lambda: None)
    bridge = SimpleNamespace(
        state=state,
        _save_arena=lambda: saved.append(1),
        _cancel_requested=False,
        job_started=SimpleNamespace(emit=lambda *a: None),
        _get_action_blocks=lambda: [],
    )
    img = SimpleNamespace(status="pending", error="", output_path="",
                          relative_path="pic.png", absolute_path="/tmp/pic.png",
                          assigned_url_id=None, attempt_count=0)
    owner = UrlRow.create("https://arena.ai", tab_id="t9")
    foreign = UrlRow.create("https://arena.ai/other", tab_id="t1")

    async def fake_baseline():
        return {}

    ctrl = SimpleNamespace(capture_baseline=fake_baseline)
    ctx = PageJobCtx(bridge=bridge, pool=pool, img=img, urls=[foreign, owner],
                     tab_id="t9", ctrl=ctrl, client=None)
    row, _corr, _job, failed, _err = await _run_image_job(ctx)
    assert failed is False
    assert row is owner and img.assigned_url_id == owner.id  # owner recorded
    assert foreign.tab_id == "t1"  # foreign row untouched, never re-linked


@pytest.mark.unit
@pytest.mark.asyncio
async def test_penalty_recorder_failure_never_breaks_the_job(monkeypatch):
    """Choke point: a broken penalty recorder degrades to a warn, job proceeds."""
    import app.services.cooldown_service as svc

    def boom(*_a, **_k):
        raise RuntimeError("recorder gone")

    monkeypatch.setattr(svc, "note_captcha_event", boom)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, ON)
    ctrl, _ = make_ctrl([True, False])
    ctx = make_ctx(pool, bridge, ctrl)
    assert await sjr.check_security(ctx) is True  # must not raise
    assert any("Captcha penalty skipped" in m for m, _ in bridge._logs)
