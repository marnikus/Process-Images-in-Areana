"""Captcha choke point owns recording start/edges/stop without changing outcome.

The recorder is a bridge-owned service (`bridge._recording_service`, see
`docs/archive/2026-09-18-captcha-session-recording/design.md`): the session
opens at detection (before any injection) and closes with the solve outcome.
RULE 9: every recording call fails open — no solve outcome may depend on it.
"""

import pytest

from app.browser.page_pool import PagePool
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha
from tests.test_captcha_service import instant_sleep, make_bridge, make_info
from tests.test_captcha_solver import FakeCtrl


class RecordingSpy:
    """Stands in for `app.services.recording.RecordingService`."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def start(self, ctrl, tab_id, detect):
        self.calls.append(("start", tab_id, detect.get("trigger"), detect.get("kind")))
        if self.fail:
            raise RuntimeError("probe install failed")

    async def edge(self, ctrl, tab_id, note, snapshot=False):
        self.calls.append(("edge", tab_id, note, bool(snapshot)))
        if self.fail:
            raise RuntimeError("snapshot failed")

    def stop(self, tab_id, status, method):
        self.calls.append(("stop", tab_id, status, method))


def _with_recorder(bridge, spy):
    """Our recorder is reachable only through the bridge attribute hook."""
    bridge._recording_service = lambda: spy
    return bridge


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manual_captcha_records_from_detect_to_outcome(monkeypatch, isolated_config_dir):
    """Overlay wait → one session: start first, terminal stop last."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    spy = RecordingSpy()
    bridge = _with_recorder(make_bridge(pool, isolated_config_dir), spy)
    ctrl = FakeCtrl(visible_seq=[True, False])

    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge,
                                              tab_id="t1", source="check-security"))

    assert outcome.status == "manual"
    assert spy.calls[0][0] == "start" and spy.calls[0][1] == "t1"
    assert spy.calls[0][2] == "check-security"  # provenance travels with the session
    assert spy.calls[-1] == ("stop", "t1", "manual", "manual")
    assert any(c[0] == "edge" and str(c[2]).startswith("outcome=manual") for c in spy.calls)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recording_failure_does_not_change_the_outcome(monkeypatch, isolated_config_dir):
    """RULE 9: a broken recorder must not stall or fail the solve."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = _with_recorder(make_bridge(pool, isolated_config_dir), RecordingSpy(fail=True))
    ctrl = FakeCtrl(visible_seq=[True, False])

    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))

    assert outcome.status == "manual"
    assert pool.get_page("t1").pending_penalty == 900  # penalty path untouched
    assert any("Recording start skipped" in m for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bridge_without_recorder_solves_normally(monkeypatch, isolated_config_dir):
    """No `_recording_service` attribute (older bridge) → solve unaffected."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)  # no recorder hook at all
    ctrl = FakeCtrl(visible_seq=[True, False])

    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))

    assert outcome.status == "manual"
    assert CaptchaService  # keep the real service in the loop (RULE 8)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_auto_solve_pins_its_own_edge(monkeypatch, isolated_config_dir):
    """The auto attempt gets a named, snapshotted edge before the outcome."""
    instant_sleep(monkeypatch)
    from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings
    from tests.test_captcha_solver import FakeClient

    import app.services.captcha.solver as solver_mod

    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    pool = PagePool()
    pool.add_page(make_info("t1"))
    spy = RecordingSpy()
    bridge = _with_recorder(make_bridge(pool, isolated_config_dir), spy)
    CaptchaKeyStore(isolated_config_dir).save(
        CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)

    outcome = await handle_captcha(CaptchaCtx(ctrl=FakeCtrl(visible_seq=[True, False]),
                                              pool=pool, bridge=bridge, tab_id="t1"))

    assert outcome.status == "solved"
    assert ("edge", "t1", "auto-solve finished: solved", True) in spy.calls
    assert spy.calls[-1] == ("stop", "t1", "solved", "auto")
