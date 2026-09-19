"""handle_captcha choke point — every call site's contract in one place.

RULE 8: real service + real PagePool + real key store/stats; only CDP and
the bridge surface are faked. Covers the RULE 9 fail-open paths (probe
error, missing service) and the penalty-record-once behaviour.
"""

from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha
from app.services.captcha.signals import SolveOutcome
from tests.test_captcha_solver import FakeCtrl, detect_result, make_env

import asyncio

import app.services.captcha.solver as solver_mod


def make_info(tab_id):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url="https://arena.ai/image/direct", status=PageStatus.STEADY,
                    is_connected=True)


def make_bridge(pool, config_dir=None, with_service=True):
    logs = []
    bridge = SimpleNamespace(
        _page_pool=pool,
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        config=SimpleNamespace(get_state=lambda k, d=None: ({"watcher_captcha_timeout_sec": 300}).get(k, d)),
        _logs=logs,
    )
    if with_service and config_dir is not None:
        bridge._captcha_service = lambda: CaptchaService(str(config_dir), bridge._log)
    return bridge


def instant_sleep(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_dialog_is_noop(monkeypatch, isolated_config_dir):
    """Detect says gone (race) → none, no penalty, no stats."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)

    class GoneCtrl(FakeCtrl):
        async def _evaluate(self, js):
            return __import__("json").dumps({"visible": False, "kind": "none", "sitekey": "", "url": ""})

    ctx = CaptchaCtx(ctrl=GoneCtrl(visible_seq=[]), pool=pool, bridge=bridge, tab_id="t1")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "none"
    assert pool.get_page("t1").pending_penalty == 0
    assert bridge._captcha_service().stats.to_dict()["detected_total"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_service_waits_manually_and_records(monkeypatch, isolated_config_dir):
    """Default policy (RULE 20): OFF → overlay + manual wait → penalty once."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, False])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", source="check-security")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    assert pool.get_page("t1").pending_penalty == 900  # default penalty
    d = bridge._captcha_service().stats.to_dict()
    assert d["detected_total"] == 1 and d["manual_solved"] == 1
    assert any("🛡️" in m for m, _ in bridge._logs)  # penalty choke-point line
    assert any("CAPTCHA_WAITING" in m and "awaiting your solve" in m for m, _ in bridge._logs)  # visual flag
    assert ctrl.overlay_calls and ctrl.overlay_calls[-1]["sub"].startswith("auto-solve OFF")  # why-not-solving flag


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enabled_service_auto_solves_and_records(monkeypatch, isolated_config_dir):
    """Opt-in path: 2Captcha token accepted → solved, penalty still stacks."""
    instant_sleep(monkeypatch)
    from tests.test_captcha_solver import FakeClient

    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    keys = CaptchaKeyStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    ctrl = FakeCtrl(visible_seq=[True, True, False])  # start up; verify gone on first check
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", source="check-security")
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)
    outcome = await handle_captcha(ctx)
    assert outcome.status == "solved"
    assert outcome.method == "auto"
    assert pool.get_page("t1").pending_penalty == 900  # auto-solved still stacks
    d = bridge._captcha_service().stats.to_dict()
    assert d["auto_solved"] == 1 and d["detected_total"] == 1
    assert len(client.created) == 1
    assert any("CAPTCHA_AUTO" in m for m, _ in bridge._logs)  # auto-solve is never silent


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_error_fails_open_to_manual(monkeypatch, isolated_config_dir):
    """RULE 9: a broken detect probe must not stall the job."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)

    class BrokenProbeCtrl(FakeCtrl):
        async def _evaluate(self, js):
            raise RuntimeError("CDP disconnected")

    ctrl = BrokenProbeCtrl(visible_seq=[True, False])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"  # degraded, not failed
    assert pool.get_page("t1").pending_penalty == 900
    assert any("detect probe failed" in m for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsolvable_kind_falls_back_to_manual(monkeypatch, isolated_config_dir):
    """Image captcha / missing sitekey → no 2Captcha task, manual wait."""
    instant_sleep(monkeypatch)
    from tests.test_captcha_solver import FakeClient

    client = FakeClient("K")
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    keys = CaptchaKeyStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16))

    class ImageCtrl(FakeCtrl):
        async def _evaluate(self, js):
            import json
            if "Security Verification" in js:
                return json.dumps({"visible": True, "kind": "image", "sitekey": "", "url": "https://x.ai"})
            return json.dumps({"ok": True})

    ctrl = ImageCtrl(visible_seq=[True, False])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    assert client.created == []  # nothing sent to 2Captcha
    assert pool.get_page("t1").pending_penalty == 900
    assert any("CAPTCHA_AUTO skipped" in m for m, _ in bridge._logs)  # skip is never silent
    assert ctrl.overlay_calls and ctrl.overlay_calls[-1]["sub"] == "auto-solve: no sitekey in dialog"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_during_manual_wait_records_nothing(monkeypatch, isolated_config_dir):
    """RULE 7: stop mid-wait → stopped, no penalty, no manual count."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, True, True])  # never clears
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1",
                     stop=lambda: True)
    outcome = await handle_captcha(ctx)
    assert outcome.status == "stopped"
    assert pool.get_page("t1").pending_penalty == 0
    assert bridge._captcha_service().stats.to_dict()["manual_solved"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bridge_without_service_still_manually_waits(monkeypatch, isolated_config_dir):
    """Old-style bridge (no _captcha_service) → manual flow, no crash."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, with_service=False)
    ctrl = FakeCtrl(visible_seq=[True, False])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    assert pool.get_page("t1").pending_penalty == 900


@pytest.mark.unit
@pytest.mark.asyncio
async def test_auto_solve_failure_falls_back_to_manual(monkeypatch, isolated_config_dir):
    """2Captcha task rejected (no credit) → warn + manual wait, not crash."""
    instant_sleep(monkeypatch)
    from tests.test_captcha_solver import FakeClient

    from app.services.captcha.api_client import ApiError
    client = FakeClient("K", exc=ApiError(1, "CAPTCHA_UNAVAILABLE"))  # poll → ApiError
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    keys = CaptchaKeyStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    ctrl = FakeCtrl(visible_seq=[True, False])  # manual wait clears
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    assert pool.get_page("t1").pending_penalty == 900
    assert any("falling back to manual wait" in m for m, _ in bridge._logs)
    assert ctrl.overlay_calls and ctrl.overlay_calls[-1]["sub"].startswith("auto-solve failed:")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_every_helper_absorbs_failures(monkeypatch, isolated_config_dir):
    """RULE 9 chaos: every internal failure degrades, never raises."""
    instant_sleep(monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    pool = PagePool()
    pool.add_page(make_info("t1"))
    page = pool.get_page("t1")
    pool.mark_waiting = boom
    pool.get_page = boom  # after we captured `page`
    bridge = make_bridge(pool, isolated_config_dir)
    bridge._emit_pool_status = boom
    bridge.config.get_state = boom
    svc = CaptchaService(str(isolated_config_dir))
    svc.stats.record = boom
    svc.stats.set_last_error = boom
    svc.stats.set_balance = boom
    bridge._captcha_service = lambda: svc  # same (broken-stats) instance

    class OverlayBoomCtrl(FakeCtrl):
        async def show_watcher_overlay(self, *a, **k):
            raise RuntimeError("overlay down")

        async def hide_watcher_overlay(self):
            raise RuntimeError("overlay down")

    ctrl = OverlayBoomCtrl(visible_seq=[True, False])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", log=boom)
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    assert page.pending_penalty == 900  # penalty survives all the chaos


@pytest.mark.unit
def test_service_factory_errors_degrade(isolated_config_dir):
    """Bridge whose _captcha_service raises → auto path skipped, no crash."""
    from app.services.captcha.service import _service

    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)

    def broken_factory():
        raise RuntimeError("ctor boom")

    bridge._captcha_service = broken_factory
    ctx = CaptchaCtx(ctrl=FakeCtrl(visible_seq=[True]), pool=pool, bridge=bridge, tab_id="t1")
    assert _service(ctx) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_balance_paths(isolated_config_dir, monkeypatch):
    """No key → None; ApiError → last_error + None; ok → balance stored."""
    import app.services.captcha.service as service_mod

    svc = CaptchaService(str(isolated_config_dir))
    assert await svc.refresh_balance() is None  # no key stored

    keys = CaptchaKeyStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16))

    class BalClient:
        def __init__(self, ok_balance):
            self._ok = ok_balance

        async def get_balance(self):
            if self._ok is None:
                from app.services.captcha.api_client import ApiError
                raise ApiError("no_credit", error_id=3)
            return self._ok

        async def aclose(self):
            return None

    monkeypatch.setattr(service_mod, "Captcha2Client", lambda key: BalClient(None))
    assert await svc.refresh_balance() is None
    assert svc.stats.last_error == "balance: no_credit"

    monkeypatch.setattr(service_mod, "Captcha2Client", lambda key: BalClient(12.34))
    assert await svc.refresh_balance() == 12.34
    assert svc.stats.last_balance == 12.34
    assert svc.stats_payload()["auto_solved"] == 0  # stats_payload reachable
    status = svc.status_payload()
    assert status["balance"] == 12.34 and status["masked_key"] == "KKKK****KKKK"


@pytest.mark.unit
def test_signal_from_result_string_and_bad_shapes():
    from app.services.captcha.signals import CaptchaSignal

    sig = CaptchaSignal.from_result('{"visible": true, "kind": "recaptcha_enterprise", "sitekey": "6Lx", "url": "https://a.ai"}')
    assert sig.visible and sig.kind == "recaptcha_enterprise" and sig.sitekey == "6Lx"
    assert CaptchaSignal.from_result("not json at all").visible is False
    assert CaptchaSignal.from_result(42).visible is False
    assert CaptchaSignal.from_result(None).visible is False


@pytest.mark.unit
def test_service_apply_settings_masks_key(isolated_config_dir):
    svc = CaptchaService(str(isolated_config_dir))
    result = svc.apply_settings("abcdef1234567890", True, 240)
    assert result["ok"] is True
    assert result["masked_key"] == "abcd****7890"
    assert "abcdef1234567890" not in str(result)  # raw key never in the payload
    assert svc.auto_enabled() is True
    payload = svc.status_payload()
    assert "abcdef1234567890" not in str(payload)
    assert payload["masked_key"] == "abcd****7890"
    assert payload["solve_timeout_sec"] == 240


def solve_reports(bridge):
    """Parse the CAPTCHA_SOLVE JSON lines from the bridge log."""
    import json

    out = []
    for m, _ in bridge._logs:
        if "🧾 CAPTCHA_SOLVE " in m:
            out.append(json.loads(m.split("🧾 CAPTCHA_SOLVE ", 1)[1]))
    return out


@pytest.mark.unit
@pytest.mark.asyncio
async def test_auto_solve_emits_structured_report(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    from tests.test_captcha_solver import SITEKEY, FakeClient

    token = "03AG" + "z" * 100 + "Q12"
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": token}},
    ])
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    keys = CaptchaKeyStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))

    class DomCtrl(FakeCtrl):
        async def _evaluate(self, js):
            import json
            if "Security Verification" in js:
                d = detect_result()
                d["dom"] = "dialog:recaptcha-iframe"
                return json.dumps(d)
            return await super()._evaluate(js)

    ctrl = DomCtrl(visible_seq=[True, True, False])  # start up; pre-inject up; verify gone
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", source="check-security")
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)
    assert (await handle_captcha(ctx)).status == "solved"
    reps = solve_reports(bridge)
    assert len(reps) == 1
    rep = reps[0]
    assert rep["v"] == 1 and len(rep["eid"]) == 8
    assert rep["tab"] == "t1" and rep["source"] == "check-security"
    assert rep["kind"] == "recaptcha_enterprise" and rep["dom"] == "dialog:recaptcha-iframe"
    assert rep["sitekey"] == SITEKEY  # full public sitekey, not masked
    assert rep["url"] == "https://arena.ai/image/direct" and rep["invisible"] is False
    assert rep["task_id"] == "101" and rep["task_type"] == "RecaptchaV2EnterpriseTaskProxyless"
    assert rep["polls"] == 1 and rep["attempts"] == 1 and rep["poll_interval_s"] == 5.0
    assert rep["token"]["fp"] == f"len={len(token)} head={token[:8]} tail={token[-4:]}"
    assert rep["dialog_at_token"] == "visible"
    assert "scope=dialog" in rep["inject"]
    assert rep["page_error"] is None
    assert rep["status"] == "solved" and rep["penalty_s"] == 900
    assert "_detected_mono" not in rep
    assert ctrl._captcha_reports == [{"eid": rep["eid"], "tab": "t1"}]  # stashed for the join


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manual_path_emits_report_without_task(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, False])  # manual wait: up, then cleared
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", source="job")
    assert (await handle_captcha(ctx)).status == "manual"  # auto OFF by default
    reps = solve_reports(bridge)
    assert len(reps) == 1
    rep = reps[0]
    assert rep["task_id"] == "" and rep["task_type"] == "" and rep["polls"] == 0
    assert rep["token"] is None and rep["inject"] == ""
    assert rep["status"] == "manual" and rep["penalty_s"] == 900
    assert ctrl._captcha_reports[0]["eid"] == rep["eid"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stopped_path_emits_report_with_zero_penalty(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, True, True])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", stop=lambda: True)
    assert (await handle_captcha(ctx)).status == "stopped"
    reps = solve_reports(bridge)
    assert len(reps) == 1  # edge data is never silent
    assert reps[0]["status"] == "stopped" and reps[0]["penalty_s"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dialog_gone_before_task_manual_fallback_is_instant(monkeypatch, isolated_config_dir):
    """H2: challenge cleared before we pay → nothing charged, instant manual resolve."""
    instant_sleep(monkeypatch)
    from tests.test_captcha_solver import FakeClient

    client = FakeClient("K")
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    keys = CaptchaKeyStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    ctrl = FakeCtrl(visible_seq=[])  # dialog already gone
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"  # the user's own solve is credited
    assert client.created == []  # nothing billed for a gone challenge
    assert any("dialog_gone_before_task" in m for m, _ in bridge._logs)


def _stub_solver_with_stale(bridge, reason):
    """Pin the bridge to ONE service instance, then stub its solver (token_stale)."""
    svc = bridge._captcha_service()
    bridge._captcha_service = lambda: svc  # the default lambda mints a fresh service

    async def fake_solve(ctrl, tab_id, sig, stop):
        return SolveOutcome(status="token_stale", reason=f"token_stale: {reason}", method="auto")

    svc.solver.solve = fake_solve


@pytest.mark.unit
@pytest.mark.asyncio
async def test_token_stale_with_visible_dialog_falls_back_to_manual(monkeypatch, isolated_config_dir):
    """H4: token stale but the challenge is still on screen → human fallback."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    keys = CaptchaKeyStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    ctrl = FakeCtrl(visible_seq=[True, False])  # H4 probe: visible; wait: cleared
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    _stub_solver_with_stale(bridge, "page_identity_changed")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    assert ctrl.overlay_calls  # watcher overlay shown for the manual solve
    assert ctrl.overlay_calls[-1]["sub"].startswith("auto-solve failed:")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_token_stale_with_gone_dialog_ends_encounter(monkeypatch, isolated_config_dir):
    """H4: challenge already cleared → token_stale stands, no pointless wait."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    keys = CaptchaKeyStore(isolated_config_dir)
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    ctrl = FakeCtrl(visible_seq=[False])  # H4 probe: already gone
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    _stub_solver_with_stale(bridge, "sitekey_changed")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "token_stale"
    assert ctrl.overlay_calls == []  # nobody can solve a cleared challenge

@pytest.mark.unit
def test_service_logging_and_penalty_helpers_fail_open(monkeypatch):
    from app.services.captcha.service import _log, _record_penalty
    import app.services.cooldown_service as cooldown
    calls = []
    bridge = SimpleNamespace(_log=lambda msg, level: calls.append((msg, level)))
    ctx = CaptchaCtx(ctrl=SimpleNamespace(), pool=None, bridge=bridge, tab_id="t1", log=lambda m, l: calls.append((m, l)))
    _log(ctx, "direct")
    ctx.log = lambda m, l: (_ for _ in ()).throw(RuntimeError("bad logger"))
    _log(ctx, "fallback")
    monkeypatch.setattr(cooldown, "note_captcha_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("broken")))
    _record_penalty(ctx)
    assert len(calls) >= 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_dialog_visibility_failure_is_closed():
    from app.services.captcha.service import _dialog_still_visible
    ctrl = SimpleNamespace(is_security_dialog_visible=lambda: (_ for _ in ()).throw(RuntimeError("gone")))
    ctx = CaptchaCtx(ctrl=ctrl, pool=None, bridge=SimpleNamespace(), tab_id="t1")
    assert await _dialog_still_visible(ctx) is False
