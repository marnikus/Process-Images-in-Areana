"""Captcha escalation-path additions (2026-09-18 round 11).

The render hook captures arena's dialog sitecallback so a 2Captcha token can
resolve the app's own token promise (docs/archive/2026-09-18-captcha-escalation-path).
RULE 8: real signal/service/solver/CDP-install code; fakes only at CDP + 2Captcha.
"""

import json
from types import SimpleNamespace

import pytest

import app.services.captcha.solver as solver_mod
from app.browser.captcha_probes import build_hook_js
from app.services.captcha.service import CaptchaCtx, _hook_desc
from app.services.captcha.signals import CaptchaSignal
from tests.test_captcha_solver import SITEKEY, URL, FakeClient, FakeCtrl, make_env, signal


@pytest.mark.unit
def test_signal_maps_hook_evidence():
    res = {"visible": True, "kind": "recaptcha_enterprise", "sitekey": SITEKEY, "url": URL,
           "hook": {"ready": True, "captured": True, "sitekey": SITEKEY, "ageSec": 2.5}}
    s = CaptchaSignal.from_result(res)
    assert s.hook == {"ready": True, "captured": True, "sitekey": SITEKEY, "ageSec": 2.5}
    assert CaptchaSignal.from_result(res | {"hook": "bogus"}).hook == {}
    assert CaptchaSignal.from_result(res | {"hook": None}).hook == {}


@pytest.mark.unit
def test_signal_without_hook_defaults_empty():
    assert signal().hook == {}


@pytest.mark.unit
def test_build_hook_js_is_the_real_hook_source():
    js = build_hook_js()
    assert "__arenaRecaptchaHook" in js and "__arenaV2Challenge" in js
    assert js.startswith("/*")  # the real file, stripped, not a stub


@pytest.mark.unit
def test_hook_desc_variants():
    cap = signal().__class__(visible=True, kind="recaptcha_enterprise", sitekey=SITEKEY,
                             page_url=URL, hook={"captured": True, "sitekey": SITEKEY, "ageSec": 5})
    d = _hook_desc(cap)
    assert d.startswith("hook=captured(sitekey=…") and "age=5s" in d
    assert _hook_desc(solver_signal({"ready": True})) == "hook=ready"
    assert _hook_desc(solver_signal({})) == "hook=absent"
    bad = solver_signal({"captured": True, "sitekey": SITEKEY, "ageSec": "bogus"})
    assert "age=?" in _hook_desc(bad)  # unparseable age never breaks the log line


def solver_signal(hook):
    return signal().__class__(visible=True, kind="recaptcha_enterprise", sitekey=SITEKEY,
                              page_url=URL, hook=hook)


@pytest.mark.unit
def test_capture_window_logged_only_when_captured():
    logs = []
    solver = solver_mod.CaptchaSolver(None, None, lambda m, l="info": logs.append(m))
    solver_mod._log_capture_window(solver,
                                   solver_signal({"captured": True, "sitekey": SITEKEY, "ageSec": 10}))
    assert len(logs) == 1
    assert "60 s dialog window" in logs[0] and "50s left" in logs[0]
    solver_mod._log_capture_window(solver, signal())  # not captured → silent
    assert len(logs) == 1


class _FakeSend:
    """CDP send double: records (method, params), scripted replies."""

    def __init__(self, replies=None, exc=None):
        self.calls = []
        self._replies = list(replies or [])
        self._exc = exc

    async def __call__(self, method, params=None, timeout=30):
        self.calls.append((method, params))
        if self._exc is not None:
            raise self._exc
        if self._replies:
            return self._replies.pop(0)
        return {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdp_install_sends_newdoc_script_and_immediate_eval(monkeypatch):
    from app.browser.cdp_client import CDPClient
    client = CDPClient()
    send = _FakeSend(replies=[{"identifier": "h1"},
                              {"result": {"value": {"installed": True, "fresh": True}}}],
                     exc=None)
    monkeypatch.setattr(client, "send", send)
    ok = await client._install_captcha_hook()
    assert ok is True
    methods = [m for m, _ in send.calls]
    assert methods == ["Page.addScriptToEvaluateOnNewDocument", "Runtime.evaluate"]
    assert send.calls[0][1]["source"] == build_hook_js()
    assert "__arenaRecaptchaHook" in send.calls[1][1]["expression"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdp_install_fail_open_on_cdp_error(monkeypatch):
    from app.browser.cdp_client import CDPClient
    client = CDPClient()
    monkeypatch.setattr(client, "send", _FakeSend(exc=RuntimeError("ws gone")))
    assert await client._install_captcha_hook() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_canonical_path_logs_resolution_and_solves(monkeypatch, isolated_config_dir):
    """inject result path=hook → the canonical-path log line + solved outcome."""
    class HookCtrl(FakeCtrl):
        async def _evaluate(self, js):
            if "g-recaptcha-response" in js:
                return json.dumps({"ok": True, "path": "hook", "cb": "hook", "cbCalled": True})
            return await super()._evaluate(js)

    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = HookCtrl(visible_seq=[False])
    outcome = await solver.solve(ctrl, "t1", solver_signal({"captured": True,
                                                            "sitekey": SITEKEY, "ageSec": 2}))
    assert outcome.status == "solved"
    assert any("canonical path" in m and "recaptchaV2Token" in m for m, _ in logs)
    assert any("challenge captured" in m and "58s left" in m for m, _ in logs)  # 60-2 window
    assert stats.to_dict()["auto_solved"] == 1


def _ctx(ctrl, logs):
    bridge = SimpleNamespace(_log=lambda m, l="info": logs.append(m))
    return CaptchaCtx(ctrl=ctrl, pool=None, bridge=bridge, tab_id="t1", source="job")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_signal_re_evaluates_hook_before_detect(monkeypatch):
    from app.services.captcha.service import detect_signal
    logs = []
    ctrl = FakeCtrl(visible_seq=[])
    sig = await detect_signal(_ctx(ctrl, logs))
    assert sig.kind == "recaptcha_enterprise"
    assert "__arenaRecaptchaHook" in ctrl.probes[0]      # defense-in-depth install
    assert "Security Verification" in ctrl.probes[1]     # then the real detect probe


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_signal_hook_error_does_not_block_detect(monkeypatch):
    from app.services.captcha.service import detect_signal

    class HookFailCtrl(FakeCtrl):
        async def _evaluate(self, js):
            if "__arenaRecaptchaHook" in js:
                raise RuntimeError("ws gone")
            return await super()._evaluate(js)

    sig = await detect_signal(_ctx(HookFailCtrl(visible_seq=[]), []))
    assert sig.kind == "recaptcha_enterprise"  # RULE 9: hook failure degrades silently


def _slow_client():
    """2Captcha double: 3 processing polls, then ready (deterministic 'slow' solve)."""
    state = {"n": 0}
    c = FakeClient("K", results=[])

    async def counting(_task_id):
        state["n"] += 1
        if state["n"] <= 3:
            return {"errorId": 0, "status": "processing"}
        return {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}}

    c.get_result = counting
    return c


def _extend_solve_timeout(solver, sec=120):
    """The 45 s warning sits past the 30 s test default — raise it like prod."""
    from app.services.captcha.key_store import CaptchaSettings
    solver._keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=sec))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_slow_window_warning_only_with_captured_challenge(monkeypatch, isolated_config_dir):
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, _slow_client(), step=20)
    _extend_solve_timeout(solver)
    await solver.solve(FakeCtrl(visible_seq=[False]), "t1",
                       solver_signal({"captured": True, "sitekey": SITEKEY, "ageSec": 0}))
    assert any("45 s into the 60 s dialog window" in m for m, _ in logs)

    solver2, _, logs2, _ = make_env(monkeypatch, isolated_config_dir, _slow_client(), step=20)
    _extend_solve_timeout(solver2)
    await solver2.solve(FakeCtrl(visible_seq=[False]), "t2", signal())  # not captured → silent
    assert not any("45 s into" in m for m, _ in logs2)
