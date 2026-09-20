"""handle_captcha choke point — the pipeline's wait-only contract in one place.

Since the 2026-10-02 isolation the pipeline NEVER solves: it detects,
pauses (overlay + poll) until the dialog clears — by the user or by the
Captcha Watcher — records stats and the cooldown penalty. RULE 8: real
service + real PagePool + real key store/stats; only CDP and the bridge
surface are faked. Covers the RULE 9 fail-open paths (probe error, missing
service) and the penalty-record-once behaviour.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha

SITEKEY = "6Lsitekey00000000000000000000"
URL = "https://arena.ai/image/direct"


def detect_result(kind="recaptcha_enterprise", sitekey=SITEKEY, url=URL):
    """Probe-shaped result (note: the probe uses the 'url' key)."""
    return {"visible": True, "kind": kind, "sitekey": sitekey, "url": url}


class FakeCtrl:
    """CDP double: dispatches probes by JS content, dialog flag by sequence."""

    def __init__(self, visible_seq, detect=None):
        self._visible = list(visible_seq)
        self._detect = detect or detect_result()
        self.probes = []
        self.overlay_calls = []
        self.cdp = SimpleNamespace(evaluate=self._evaluate)

    async def _evaluate(self, js):
        self.probes.append(js)
        if "Security Verification" in js:  # detect probe (unique marker)
            return json.dumps(self._detect)
        return json.dumps({"ok": True})

    async def is_security_dialog_visible(self):
        return self._visible.pop(0) if self._visible else False

    async def show_watcher_overlay(self, *a, **k):
        self.overlay_calls.append(k)
        return True

    async def hide_watcher_overlay(self):
        return True


def make_info(tab_id):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url=URL, status=PageStatus.STEADY, is_connected=True)


def make_bridge(pool, config_dir=None, with_service=True):
    logs = []
    bridge = SimpleNamespace(
        _page_pool=pool,
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        config=SimpleNamespace(get_state=lambda k, d=None: ({"watcher_captcha_timeout_sec": 300, "watcher_enabled": True}).get(k, d)),
        _logs=logs,
    )
    if with_service and config_dir is not None:
        svc = CaptchaService(str(config_dir), bridge._log)
        bridge._captcha_service = lambda: svc
    return bridge


def instant_sleep(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


def solve_reports(bridge):
    """Parse the CAPTCHA_SOLVE JSON lines from the bridge log."""
    out = []
    for m, _ in bridge._logs:
        if "🧾 CAPTCHA_SOLVE " in m:
            out.append(json.loads(m.split("🧾 CAPTCHA_SOLVE ", 1)[1]))
    return out


def probe_payloads(ctrl):
    """Every JS the pipeline evaluated on the page (detect only — never inject)."""
    return ctrl.probes


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_dialog_is_noop(monkeypatch, isolated_config_dir):
    """Detect says gone (race) → none, no penalty, no stats."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[], detect={"visible": False, "kind": "none", "sitekey": "", "url": ""})
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "none"
    assert pool.get_page("t1").pending_penalty == 0
    assert bridge._captcha_service().stats.to_dict()["detected_total"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_waits_and_records_never_solves(monkeypatch, isolated_config_dir):
    """Default policy (RULE 20): overlay + wait → penalty once; no inject probe ever."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, False])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", source="check-security")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual" and outcome.method == "manual"
    assert pool.get_page("t1").pending_penalty == 900  # default penalty
    d = bridge._captcha_service().stats.to_dict()
    assert d["detected_total"] == 1 and d["manual_solved"] == 1
    assert any("CAPTCHA_WAITING" in m and "awaiting your solve" in m for m, _ in bridge._logs)
    # D-15 (S3): the no-key branch no longer advertises the Watcher; it states the pause.
    assert ctrl.overlay_calls and "the generation timeout is paused" in ctrl.overlay_calls[-1]["sub"]
    assert all("findCfgCallback" not in js for js in probe_payloads(ctrl))  # never injects


@pytest.mark.unit
@pytest.mark.asyncio
async def test_key_present_does_not_make_pipeline_solve(monkeypatch, isolated_config_dir):
    """A stored key + legacy enabled flag change nothing: only the Watcher solves."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    CaptchaKeyStore(isolated_config_dir).save(CaptchaSettings(enabled=True, api_key="K" * 16))
    ctrl = FakeCtrl(visible_seq=[True, False])
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "manual"
    assert not any("CAPTCHA_AUTO" in m for m, _ in bridge._logs)
    assert all("findCfgCallback" not in js for js in probe_payloads(ctrl))  # inject.js marker
    assert bridge._captcha_service().stats.to_dict()["auto_solved"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_watcher_running_labels_the_wait(monkeypatch, isolated_config_dir):
    """Watcher ON → the overlay says who is solving; outcome method = watcher."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    bridge._captcha_watcher = SimpleNamespace(running=True)
    bridge._captcha_service().apply_settings("TESTKEY", 300)  # D-15 (S3): solving words need a key AND a running loop
    ctrl = FakeCtrl(visible_seq=[True, False])
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "manual" and outcome.method == "watcher"
    assert ctrl.overlay_calls[-1]["sub"].startswith("Captcha Watcher is solving")
    assert pool.get_page("t1").pending_penalty == 900


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_error_fails_open_to_wait(monkeypatch, isolated_config_dir):
    """RULE 9: a broken detect probe must not stall the job."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)

    class BrokenProbeCtrl(FakeCtrl):
        async def _evaluate(self, js):
            raise RuntimeError("CDP disconnected")

    ctrl = BrokenProbeCtrl(visible_seq=[True, False])
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "manual"  # degraded, not failed
    assert pool.get_page("t1").pending_penalty == 900
    assert any("detect probe failed" in m for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsolvable_kind_waits_like_any_other(monkeypatch, isolated_config_dir):
    """Image captcha / missing sitekey → same wait path, penalty once."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, False],
                    detect={"visible": True, "kind": "image", "sitekey": "", "url": "https://x.ai"})
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "manual"
    assert pool.get_page("t1").pending_penalty == 900
    assert any("sitekey=missing" in m for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_during_wait_records_nothing(monkeypatch, isolated_config_dir):
    """RULE 7: stop mid-wait → stopped, no penalty, no manual count."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, True, True])  # never clears
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", stop=lambda: True)
    outcome = await handle_captcha(ctx)
    assert outcome.status == "stopped"
    assert pool.get_page("t1").pending_penalty == 0
    assert bridge._captcha_service().stats.to_dict()["manual_solved"] == 0
    reps = solve_reports(bridge)
    assert len(reps) == 1 and reps[0]["status"] == "stopped" and reps[0]["penalty_s"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bridge_without_service_still_waits(monkeypatch, isolated_config_dir):
    """Old-style bridge (no _captcha_service) → wait flow, no crash."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, with_service=False)
    ctrl = FakeCtrl(visible_seq=[True, False])
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "manual"
    assert pool.get_page("t1").pending_penalty == 900


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
    # S2: the scope lookup must answer for the wait path to run; every other read still explodes.
    bridge.config.get_state = lambda k, d=None: True if k == "watcher_enabled" else boom(k, d)
    bridge._captcha_watcher = SimpleNamespace()  # no `running` attr → fail closed
    svc = CaptchaService(str(isolated_config_dir))
    svc.stats.record = boom
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
    """Bridge whose _captcha_service raises → stats skipped, no crash."""
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
def test_signal_from_result_string_and_bad_shapes():
    from app.services.captcha.signals import CaptchaSignal

    sig = CaptchaSignal.from_result('{"visible": true, "kind": "recaptcha_enterprise", "sitekey": "6Lx", "url": "https://a.ai"}')
    assert sig.visible and sig.kind == "recaptcha_enterprise" and sig.sitekey == "6Lx"
    assert CaptchaSignal.from_result("not json at all").visible is False
    assert CaptchaSignal.from_result(42).visible is False
    assert CaptchaSignal.from_result(None).visible is False


@pytest.mark.unit
def test_service_apply_settings_masks_key_and_never_enables(isolated_config_dir):
    svc = CaptchaService(str(isolated_config_dir))
    result = svc.apply_settings("abcdef1234567890", 240)
    assert result["ok"] is True and result["enabled"] is False
    assert result["masked_key"] == "abcd****7890"
    assert "abcdef1234567890" not in str(result)  # raw key never in the payload
    payload = svc.status_payload()
    assert "abcdef1234567890" not in str(payload)
    assert payload["masked_key"] == "abcd****7890"
    assert payload["solve_timeout_sec"] == 240 and payload["enabled"] is False
    assert svc.stats_payload()["auto_solved"] == 0  # stats_payload reachable
    assert not hasattr(svc, "solver")  # the service owns no solving mechanic


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_path_emits_report_without_task(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, False])  # wait: up, then cleared
    ctrl._detect = {**detect_result(), "dom": "dialog:recaptcha-iframe"}
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", source="job")
    assert (await handle_captcha(ctx)).status == "manual"
    reps = solve_reports(bridge)
    assert len(reps) == 1
    rep = reps[0]
    assert rep["v"] == 1 and len(rep["eid"]) == 8
    assert rep["tab"] == "t1" and rep["source"] == "job"
    assert rep["kind"] == "recaptcha_enterprise" and rep["dom"] == "dialog:recaptcha-iframe"
    assert rep["sitekey"] == SITEKEY and rep["url"] == URL
    assert rep["task_id"] == "" and rep["task_type"] == "" and rep["polls"] == 0
    assert rep["token"] is None and rep["inject"] == ""
    assert rep["status"] == "manual" and rep["method"] == "manual" and rep["penalty_s"] == 900
    assert "_detected_mono" not in rep
    assert ctrl._captcha_reports == [{"eid": rep["eid"], "tab": "t1"}]  # stashed for the join
