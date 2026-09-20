"""Start gate — one batch at a time (B13, I-45; S5: the run is always-live).

S5 armed (2026-09-20): `check_start_ready` now owns only the CDP gate —
the run-state / batch-future gates moved to the always-live supervisor
(S5, I-47). A second Start while live wakes the loop (`🟢 Run already
live`) instead of `⚠ Already running`; only an unwinding cancel still
refuses with `batch still active`. RULE 8: the real `RunControlMixin.
start_run` slot runs on a stub host with a live Future.
"""

import json
from concurrent.futures import Future

import pytest

from app.core.models import UrlRow
from app.ui.panels import run_control as rc
from app.ui.panels.run_control import RunControlMixin
from tests.test_multi_page_dispatcher_run import make_img
from tests.test_panel_slots import make_cdp, make_host, make_state


def ready_host(run_state, future, monkeypatch):
    """Host that passes every other gate (prompt, selection, URL, CDP)."""
    scheduled = []
    # S4 armed: start_run schedules via schedule_batch (name-sniffing deleted)
    monkeypatch.setattr(rc, "schedule_batch", lambda self, coro: scheduled.append(coro) or coro)
    img = make_img()
    img.selected, img.status = True, "pending"
    state = make_state(images=[img], urls=[UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")])
    host, logs = make_host((RunControlMixin,), state=state, cdp=make_cdp(connected=True),
                           _cancel_requested=False, _pause_requested=True, _stop_after=True,
                           _run_state=run_state, _batch_future=future, _page_pool=None)
    return host, logs, scheduled


@pytest.mark.parametrize("run_state", ["paused", "stopping", "idle"])
def test_start_wakes_when_live_instead_of_scheduling_second_batch(run_state, monkeypatch):
    # S5 armed: a live future no longer refuses with "batch still active" —
    # the always-live run is woken and the queue is re-checked (S5,
    # I-47). Only an unwinding cancel still refuses.
    host, logs, scheduled = ready_host(run_state, Future(), monkeypatch)
    res = json.loads(host.start_run())
    assert res == {"ok": True, "live": True}
    assert scheduled == [], "no second batch may be scheduled — the live run is woken"
    # the old loop keeps seeing its flags — nothing was reset
    assert (host._pause_requested, host._stop_after, host._run_state) == (True, True, run_state)
    assert any("Run already live" in msg for _, msg in logs)


def test_start_refused_only_while_unwinding(monkeypatch):
    # S5 armed: the ONLY refusal for a live future is an unwinding cancel
    # (the bg loop is still joining). The wake path above handles every
    # other live case.
    host, logs, scheduled = ready_host("idle", Future(), monkeypatch)
    host._cancel_requested = True
    res = json.loads(host.start_run())
    assert res == {"ok": False, "error": "batch still active"}
    assert scheduled == []
    assert any("Resume or Cancel" in msg for _, msg in logs)


def test_start_allowed_once_the_future_is_done(monkeypatch):
    done = Future()
    done.set_result(None)
    host, _, scheduled = ready_host("idle", done, monkeypatch)
    assert json.loads(host.start_run())["ok"] is True
    assert len(scheduled) == 1 and host._run_state == "running"
    assert (host._pause_requested, host._stop_after) == (False, False)
    for coro in scheduled:
        coro.close()


def test_running_label_now_wakes_instead_of_refusing(monkeypatch):
    # S5 armed: `⚠ Already running` is replaced by `🟢 Run already live`
    # — the run never ends on its own, so a second Start re-checks the
    # queue instead of a second `run_live` (S5, I-47).
    host, logs, scheduled = ready_host("running", Future(), monkeypatch)
    res = json.loads(host.start_run())
    assert res == {"ok": True, "live": True}
    assert scheduled == []
    assert any("Run already live" in msg for _, msg in logs)


def test_check_start_ready_gate_order():
    """CDP is the only `check_start_ready` gate now (S5); the live gate
    moved to `start_run` → `_wake_live_or_none` (I-47)."""
    host, _ = make_host((RunControlMixin,), cdp=None, _run_state="idle", _batch_future=Future())
    assert json.loads(rc.check_start_ready(host))["error"] == "cdp not connected"
    host.cdp = make_cdp(connected=True)
    # a live future no longer blocks `check_start_ready` — it is handled
    # by `_wake_live_or_none` as a wake, not a refusal
    assert rc.check_start_ready(host) is None
    host._batch_future = None
    assert rc.check_start_ready(host) is None



