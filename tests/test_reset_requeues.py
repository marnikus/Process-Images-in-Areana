"""S4 — D-6R: every reset puts images back selected, through the one funnel, and the
wake fires. Pre-S3 semantics (`selected=False`) are pinned as gone."""

import inspect
import json
from types import SimpleNamespace

import pytest

from app.services.live import feed
from app.services.live.bus import live_bus
from app.ui.panels import run_control as rc_mod
from app.ui.panels.run_control import RunControlMixin
from tests.test_multi_page_dispatcher_run import make_img
from tests.test_panel_slots import make_cdp, make_host, make_state

pytestmark = pytest.mark.unit


def img_with(name, status=None, **kw):
    """make_img ignores `status`; set it post-construction."""
    img = make_img(name, **kw)
    if status is not None:
        img.status = status
    return img


def _host(images, monkeypatch, extra=None):
    pushes = []
    monkeypatch.setattr(feed, "_UNDO_HOOK",
                        lambda b: pushes.append(b.undo_service.peek()))
    attrs = dict(state=make_state(images=images), config=None, cdp=make_cdp(connected=True),
                 undo_service=SimpleNamespace(peek=lambda: "snap"),
                 _cancel_requested=False, _pause_requested=False,
                 _stop_after=False, _run_state="idle", _batch_future=None)
    attrs.update(extra or {})
    host, logs = make_host((RunControlMixin,), **attrs)
    return host, logs, pushes


def test_reset_all_requeues_everything_selected(monkeypatch):
    done = img_with("done.png", status="completed"); done.selected = False
    err = img_with("err.png", status="failed"); err.error = "boom"; err.attempt_count = 3
    host, logs, pushes = _host([done, err], monkeypatch)

    assert json.loads(host.reset_all())["ok"] is True

    for img in (done, err):
        assert img.status == "pending"
        assert img.selected is True                       # D-6R: the reversal of the old False
        assert img.error is None and img.attempt_count == 0
        assert img.output_path is None and img.assigned_url_id is None
    fed = feed.eligible_images(host.state.images)
    assert {i.filename for i in fed} == {"done.png", "err.png"}
    assert pushes == ["snap"]                             # one undo snapshot through the funnel
    assert live_bus(host).reasons() == ["reset_all"]
    assert any("Reset all: 2 images re-queued" in m for _l, m in logs)


def test_reset_image_requeues_that_image_selected(monkeypatch):
    img = img_with("one.png", status="completed"); img.selected = False
    host, _logs, pushes = _host([img], monkeypatch)

    assert json.loads(host.reset_image("i-one.png"))["ok"] is True

    assert img.status == "pending" and img.selected is True
    assert pushes == ["snap"]
    assert live_bus(host).reasons() == ["reset_image"]
    assert json.loads(host.reset_image("ghost"))["ok"] is False


def test_retry_paths_wake_with_their_reason(monkeypatch):
    img = img_with("f.png", status="failed"); img.error = "x"
    host, _logs, _pushes = _host([img], monkeypatch)
    assert json.loads(host.retry_failed())["ok"] is True
    assert live_bus(host).reasons() == ["retry_failed"]
    img.status = "failed"; img.error = "x"
    assert json.loads(host.retry_image("i-f.png"))["ok"] is True
    assert live_bus(host).reasons() == ["retry_image"]


def test_reset_image_state_has_no_selection_parameter():
    """The False could never come back as long as the parameter stays deleted."""
    assert list(inspect.signature(rc_mod.reset_image_state).parameters) == ["img"]


def test_start_run_recovers_stale_processing_before_scheduling(monkeypatch):
    from app.core.models import UrlRow

    crashed = img_with("crashed.png", status="processing")
    stale = img_with("stale.png", status="processing")
    scheduled = []

    def fake_schedule(bridge, coro):
        scheduled.append(feed.eligible_images(bridge.state.images))
        coro.close()
        return object()                                # truthy future marker for start_run

    monkeypatch.setattr(rc_mod, "schedule_batch", fake_schedule)
    monkeypatch.setattr(feed, "_UNDO_HOOK", None)
    pool_holding_crashed = SimpleNamespace(_pages={})
    from app.browser.page_pool import PagePool
    from app.services import cooldown_service

    pool = PagePool()
    pool.add_page(_pi("t1"))
    cooldown_service.set_tab_image(pool, "t1", "crashed.png")
    host, _logs, _p = _host(
        [crashed, stale], monkeypatch,
        extra=dict(_page_pool=pool,
                   state=make_state(images=[crashed, stale],
                                    urls=[UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")]),
                   config=SimpleNamespace(get_state=lambda k, d=None: d)))
    pool_holding_crashed = pool

    assert json.loads(host.start_run())["ok"] is True

    assert crashed.status == "processing"                  # live job: not touched
    assert stale.status == "pending" and stale.selected is True
    assert scheduled and [i.filename for i in scheduled[0]] == ["stale.png"]


def test_queue_scan_undo_hook_is_installed_by_the_panel_module():
    """Layer-legal wiring: services never import ui; queue_scan registers the hook."""
    from app.ui.panels import queue_scan

    assert feed._UNDO_HOOK is queue_scan.push_queue_undo
    assert queue_scan.push_queue_undo.__module__ == "app.ui.panels.queue_scan"


def _pi(tab_id):
    from app.browser.page_status import PageInfo, PageStatus

    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=tab_id,
                    url="https://x", status=PageStatus.STEADY, is_connected=True)
