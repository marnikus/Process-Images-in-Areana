"""Start gate — one live run at a time (B13, I-45; S5 D-5).

Before B13 `check_start_ready` refused only `_run_state == "running"`; after
Pause (`paused`) or Stop-after-current (`stopping`) a second Start was
accepted AND reset `_pause_requested` / `_stop_after`, which woke the old
loop — two loops on one tab, completed images sent again. Since S5 the run is
always live: Start while the future is alive never schedules a second loop
and never touches the flags — it re-checks the queue and wakes the loop
(`🟢 Run already live`). RULE 8: the real `RunControlMixin.start_run` slot
runs on a stub host with a live Future.
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
    # S4: the panel goes through the real run_state.schedule_batch; only the loop submit is faked
    from app.services import run_state as rs_mod
    monkeypatch.setattr(rs_mod, "schedule_coro", lambda self, coro: scheduled.append(coro) or coro.close() or coro)
    img = make_img()
    img.selected, img.status = True, "pending"
    state = make_state(images=[img], urls=[UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")])
    host, logs = make_host((RunControlMixin,), state=state, cdp=make_cdp(connected=True),
                           _cancel_requested=False, _pause_requested=True, _stop_after=True,
                           _run_state=run_state, _batch_future=future, _page_pool=None)
    return host, logs, scheduled


@pytest.mark.parametrize("run_state", ["paused", "stopping", "idle", "running"])
def test_start_while_the_future_is_alive_wakes_the_live_run(run_state, monkeypatch):
    from app.services.live.bus import live_bus
    host, logs, scheduled = ready_host(run_state, Future(), monkeypatch)
    res = json.loads(host.start_run())
    assert res == {"ok": True, "live": True, "queued": 1}
    assert scheduled == [], "no second loop may be scheduled"
    # the live loop keeps seeing its flags — nothing was reset (I-45 still holds)
    assert (host._pause_requested, host._stop_after, host._run_state) == (True, True, run_state)
    assert live_bus(host).reasons() == ["start"]
    assert any("🟢 Run already live — queue re-checked (1 queued)" in msg for _, msg in logs)
    assert not any("Already running" in msg or "Resume or Cancel" in msg for _, msg in logs)


def test_start_allowed_once_the_future_is_done(monkeypatch):
    done = Future()
    done.set_result(None)
    host, _, scheduled = ready_host("idle", done, monkeypatch)
    assert json.loads(host.start_run())["ok"] is True
    assert len(scheduled) == 1 and host._run_state == "running"
    assert (host._pause_requested, host._stop_after) == (False, False)
    for coro in scheduled:
        coro.close()


def test_running_label_without_a_future_is_still_refused(monkeypatch):
    """A detached run (no bg loop ⇒ no future to track) keeps the old refusal."""
    host, logs, scheduled = ready_host("running", None, monkeypatch)
    assert json.loads(host.start_run())["error"] == "already running"
    assert scheduled == []


def test_check_start_ready_gate_order():
    """CDP first, then the untracked-run label; a live future is `start_run`'s business, not the gate's."""
    host, _ = make_host((RunControlMixin,), cdp=None, _run_state="idle", _batch_future=Future())
    assert json.loads(rc.check_start_ready(host))["error"] == "cdp not connected"
    host.cdp = make_cdp(connected=True)
    assert rc.check_start_ready(host) is None
    host._run_state = "running"
    assert json.loads(rc.check_start_ready(host))["error"] == "already running"
