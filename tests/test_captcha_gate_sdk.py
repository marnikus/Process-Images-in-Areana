"""REFACTOR 02 — the captcha gate is the ONLY solve choke point (headless).

Acceptance (docs/02_refactor_plan.md):
* Watcher off  -> no network call, reason == "watcher_off".
* Watcher on   -> per-page solve with good/bad report to 2captcha.
* Per-tab in-flight lock: two tabs never share one token.
"""
import threading

import pytest

from app.services.captcha import sdk_client
from app.services.captcha.sdk_client import SDK_AVAILABLE, SdkConfig, SdkSolver
from app.services.captcha.signals import CaptchaSignal, SolveOutcome
from app.services.captcha import watcher_gate
from app.services.captcha.watcher_gate import (
    CaptchaGate,
    WATCHER_OFF,
    ALREADY_RUNNING,
    DISABLED,
)


def _sig(**over) -> CaptchaSignal:
    base = dict(kind="recaptcha_v2", sitekey="sk", page_url="https://x.test")
    base.update(over)
    return CaptchaSignal(**base)


class _StubSolver:
    """Replaces watcher_gate.SdkSolver — asserts the network never runs."""

    def __init__(self, config, logger=None):
        self.config = config
        self.reports = []

    def solve(self, sig):
        raise AssertionError("network solve attempted")

    def report(self, task_id, good):
        self.reports.append((task_id, good))


def _gate(watcher=True, solving=True) -> CaptchaGate:
    return CaptchaGate(lambda: watcher,
                       lambda: SdkConfig(api_key="k"),
                       lambda: solving)


# --- the gate decides, never the loop --------------------------------------

def test_watcher_off_skips_without_network(monkeypatch):
    monkeypatch.setattr(watcher_gate, "SdkSolver", _StubSolver)
    gate = _gate(watcher=False)
    out = gate.solve_if_watcher_on("tabA", _sig())
    assert out.skipped is True and out.ok is False
    assert out.reason == WATCHER_OFF
    assert gate.state.skipped == 1
    assert gate.state.last_reason["tabA"] == WATCHER_OFF
    assert gate.state.solved == 0


def test_solving_disarmed_skips(monkeypatch):
    monkeypatch.setattr(watcher_gate, "SdkSolver", _StubSolver)
    gate = _gate(solving=False)
    out = gate.solve_if_watcher_on("tabA", _sig())
    assert out.reason == DISABLED and out.skipped is True


def test_why_disabled_precedence():
    assert _gate(watcher=False, solving=False).why_disabled() == WATCHER_OFF
    assert _gate(watcher=True, solving=False).why_disabled() == DISABLED
    assert _gate().why_disabled() == ""
    assert _gate().is_solving_enabled() is True
    assert _gate(watcher=False).is_solving_enabled() is False


# --- per-tab in-flight lock --------------------------------------------------

def test_second_solve_same_tab_is_skipped(monkeypatch):
    started, release = threading.Event(), threading.Event()
    solved_outcome = SolveOutcome(ok=True, token="tok")

    class _Slow(_StubSolver):
        def solve(self, sig):
            started.set()
            release.wait(5)
            return solved_outcome

    monkeypatch.setattr(watcher_gate, "SdkSolver", _Slow)
    gate = _gate()
    result = {}

    def worker():
        result["out"] = gate.solve_if_watcher_on("tabA", _sig())

    t = threading.Thread(target=worker)
    t.start()
    assert started.wait(5)
    try:
        assert "tabA" in gate.state.in_flight
        # same page again while the first solve is in flight
        busy = gate.solve_if_watcher_on("tabA", _sig())
        assert busy.reason == ALREADY_RUNNING and busy.skipped is True
        # a DIFFERENT page is unaffected (per-tab, not global)
        other = CaptchaGate(lambda: True, lambda: SdkConfig(api_key="k"))
        assert "tabB" not in other.state.in_flight
    finally:
        release.set()
        t.join(5)
    assert result["out"].ok is True and result["out"].token == "tok"
    assert result["out"].tab_id == "tabA"
    assert gate.state.in_flight == {}  # released in finally
    assert gate.state.solved == 1


# --- success path + report feedback ------------------------------------------

def test_success_reports_good_token(monkeypatch):
    reports = []

    class _Ok(_StubSolver):
        def solve(self, sig):
            return SolveOutcome(ok=True, token="t1", task_id="42")

        def report(self, task_id, good):
            reports.append((task_id, good))

    monkeypatch.setattr(watcher_gate, "SdkSolver", _Ok)
    gate = _gate()
    out = gate.solve_if_watcher_on("tabA", _sig())
    assert out.ok is True and out.token == "t1"
    assert gate.state.solved == 1
    assert gate.state.last_reason["tabA"] == "solved"
    gate.report("42", True)
    assert reports == [("42", True)]


def test_failure_counts_and_keeps_reason(monkeypatch):
    class _Bad(_StubSolver):
        def solve(self, sig):
            return SolveOutcome(ok=False, reason="network", retryable=True)

    monkeypatch.setattr(watcher_gate, "SdkSolver", _Bad)
    gate = _gate()
    out = gate.solve_if_watcher_on("tabA", _sig())
    assert out.ok is False and out.reason == "network"
    assert gate.state.failed == 1
    assert gate.state.last_reason["tabA"] == "network"


def test_status_shape():
    gate = _gate(watcher=False)
    gate.solve_if_watcher_on("t1", _sig())
    st = gate.status()
    assert st["enabled"] is False
    assert st["reason"] == WATCHER_OFF
    assert st["in_flight"] == []
    assert st["solved"] == 0 and st["skipped"] == 1 and st["failed"] == 0
    assert st["last_reason"] == {"t1": WATCHER_OFF}


# --- process-wide gate registry ----------------------------------------------

def test_gate_registry(monkeypatch):
    monkeypatch.setattr(watcher_gate, "_GATE", None)
    assert watcher_gate.current_gate() is None
    assert watcher_gate.is_solving_enabled() is False
    g = _gate(watcher=False)
    assert watcher_gate.install_gate(g) is g
    assert watcher_gate.current_gate() is g
    assert watcher_gate.is_solving_enabled() is False  # watcher off


# --- SdkSolver (adapter) ------------------------------------------------------

def test_available_no_key_or_missing_sdk():
    cfg = SdkConfig(api_key="  ")
    ok, reason = SdkSolver(cfg).available()
    assert ok is False
    assert reason  # key hint or SDK hint depending on env
    if not SDK_AVAILABLE:
        assert "2captcha-python" in reason


def test_solve_unknown_kind_never_raises(monkeypatch):
    monkeypatch.setattr(sdk_client, "SDK_AVAILABLE", True)  # pass availability
    s = SdkSolver(SdkConfig(api_key="k"))
    out = s.solve(_sig(kind="nope"))
    assert out.ok is False and "unsupported kind" in out.reason


def test_solve_dispatch_kwargs(monkeypatch):
    calls = {}

    class _Client:
        def recaptcha(self, **kw):
            calls["recaptcha"] = kw
            return {"code": "TOK", "captchaId": 7}

        def hcaptcha(self, **kw):
            calls["hcaptcha"] = kw
            return {"code": "TOK", "captchaId": 8}

        def turnstile(self, **kw):
            calls["turnstile"] = kw
            return {"code": "", "captchaId": 9}

    solver = SdkSolver(SdkConfig(api_key="k"))
    monkeypatch.setattr(solver, "_client", lambda: _Client())
    monkeypatch.setattr(sdk_client, "SDK_AVAILABLE", True)

    out = solver.solve(_sig())
    assert out.ok is True and out.token == "TOK" and out.task_id == "7"
    assert calls["recaptcha"]["sitekey"] == "sk"
    assert "enterprise" not in calls["recaptcha"]

    # enterprise/invisible are signal properties, not construction fields
    solver.solve(_sig(kind="recaptcha_enterprise"))
    assert calls["recaptcha"]["enterprise"] == 1
    assert calls["recaptcha"].get("invisible") in (None, 0)

    out = solver.solve(_sig(kind="recaptcha_v3", is_invisible=True,
                            action="submit", min_score=0.5, data_s="x=1"))
    kw = calls["recaptcha"]
    assert kw["version"] == "v3" and kw["min_score"] == 0.5
    assert kw["invisible"] == 1
    assert kw["action"] == "submit" and kw["datas"] == "x=1"

    solver.solve(_sig(kind="hcaptcha"))
    assert calls["hcaptcha"] == {"sitekey": "sk", "url": "https://x.test"}

    out = solver.solve(_sig(kind="turnstile"))
    assert out.ok is False and out.reason == "empty token"


@pytest.mark.skipif(not SDK_AVAILABLE,
                    reason="exception mapping needs the real 2captcha SDK types")
def test_solve_exception_mapping(monkeypatch):
    from two_captcha import ApiException, NetworkException, TimeoutException, \
        ValidationException

    class _Boom:
        def __init__(self, exc):
            self._exc = exc

        def recaptcha(self, **kw):
            raise self._exc("x")

    for exc_type, want_reason, want_retry in (
            (ValidationException, "bad_request", False),
            (NetworkException, "network", True),
            (TimeoutException, "timeout", True),
            (ApiException, "api_error", True)):
        solver = SdkSolver(SdkConfig(api_key="k"))
        monkeypatch.setattr(solver, "_client", lambda: _Boom(exc_type("x")))
        monkeypatch.setattr(sdk_client, "SDK_AVAILABLE", True)
        out = solver.solve(_sig())
        assert out.ok is False and out.reason == want_reason
        assert out.retryable is want_retry

    solver = SdkSolver(SdkConfig(api_key="k"))
    monkeypatch.setattr(solver, "_client", lambda: _Boom(RuntimeError("x")))
    out = solver.solve(_sig())
    assert out.reason == "unexpected" and out.retryable is False


def test_report_skips_empty_task_id(monkeypatch):
    seen = []

    class _Client:
        def report(self, task_id, good):
            seen.append((task_id, good))

    solver = SdkSolver(SdkConfig(api_key="k"))
    monkeypatch.setattr(solver, "_client", lambda: _Client())
    solver.report("", True)
    assert seen == []
    solver.report("9", False)
    assert seen == [("9", False)]
