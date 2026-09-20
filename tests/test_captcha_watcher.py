"""CaptchaWatcher — the app's only solver: tick/scan/solve/inject, budgets, fail-open.

RULE 8: real watcher + real probes (the exact detect/inject JS strings) +
real SdkSolver with a fake SDK client (no network). Only the page
evaluation seam is faked.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.captcha_watcher import (
    MAX_SOLVE_ATTEMPTS,
    CaptchaSignal,
    CaptchaWatcher,
    SdkSolver,
    SolveResult,
    WatcherDeps,
    WatcherStatus,
)
from app.services.captcha_watcher import probes

SITEKEY = "6Lsitekey00000000000000000000"
URL = "https://arena.ai/image/direct"
TOKEN = "03AG" + "z" * 80


def detect_payload(visible=True, kind="recaptcha_enterprise", sitekey=SITEKEY, invisible=False):
    return {"visible": visible, "kind": kind, "sitekey": sitekey, "invisible": invisible, "url": URL}


class FakeSdk:
    """Stands in for twocaptcha.AsyncTwoCaptcha (recaptcha + balance)."""

    def __init__(self, token=TOKEN, exc=None, balance=12.5):
        self.token, self.exc, self._balance = token, exc, balance
        self.calls = []

    async def recaptcha(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return {"captchaId": "task-1", "code": self.token}

    async def balance(self):
        return self._balance


class FakePages:
    """Per-tab detect payload + inject result; records every evaluated JS."""

    def __init__(self, detect, inject_ok=True):
        self.detect = dict(detect)          # tab_id → payload (or callable)
        self.inject_ok = inject_ok
        self.evaluated = []                 # (tab_id, kind)

    async def evaluate(self, tab_id, js):
        if "findCfgCallback" in js:         # inject.js marker
            self.evaluated.append((tab_id, "inject"))
            return {"ok": self.inject_ok, "scope": "dialog", "fields": 1,
                    "cbSource": "data-callback:onSolve", "cbCalled": True}
        self.evaluated.append((tab_id, "detect"))
        payload = self.detect.get(tab_id)
        return payload() if callable(payload) else payload


def make_watcher(pages, tabs, sdk=None, key="K" * 16):
    logs = []
    statuses = []
    solver = SdkSolver(key, client_factory=lambda k, t: sdk or FakeSdk()) if key else None
    deps = WatcherDeps(
        tabs=lambda: tabs,
        evaluate=pages.evaluate,
        solver_factory=lambda: solver,
        log=lambda m, l="info": logs.append((m, l)),
        on_status=lambda p: statuses.append(p),
    )
    w = CaptchaWatcher(deps, tick_sec=1)
    w._logs, w._statuses = logs, statuses
    return w


@pytest.mark.unit
def test_signal_from_result_uses_existing_probe_contract():
    sig = CaptchaSignal.from_result(detect_payload(kind="recaptcha_v2", invisible=True))
    assert sig.visible and sig.solvable and sig.invisible and sig.page_url == URL
    assert CaptchaSignal.from_result({"visible": True, "kind": "hcaptcha", "sitekey": "x"}).solvable is False
    assert CaptchaSignal.from_result({"visible": True, "kind": "recaptcha_v2", "sitekey": ""}).solvable is False
    assert CaptchaSignal.from_result(None, URL).visible is False
    assert CaptchaSignal.from_result("garbage").visible is False


@pytest.mark.unit
def test_probes_are_the_verified_browser_probes():
    """The watcher evaluates the same detect/inject sources tests/js/test_captcha.mjs runs."""
    assert "Security Verification" in probes.detect_js()  # badge-aware detect probe
    js = probes.inject_js(TOKEN, SITEKEY)
    assert js.startswith("(") and js.endswith(f")({json.dumps(TOKEN)}, {json.dumps(SITEKEY)})")
    assert probes.inject_ok({"ok": True}) and not probes.inject_ok(None)
    summary = probes.inject_summary({"ok": False, "error": "response field not found"})
    assert summary == {"ok": False, "scope": "", "fields": 0, "cb": "none",
                       "cb_called": False, "error": "response field not found"}
    assert probes.inject_summary("x") == {"ok": False, "error": "no result"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tick_solves_visible_challenge_and_injects():
    sdk = FakeSdk()
    pages = FakePages({"t1": detect_payload(), "t2": detect_payload(visible=False)})
    w = make_watcher(pages, [{"id": "t1", "url": URL}, {"id": "t2", "url": URL}], sdk=sdk)
    assert await w.tick() == 2
    st = w.status()
    assert st["solved_total"] == 1 and st["failed_total"] == 0 and st["tabs_seen"] == 2
    assert sdk.calls == [{"sitekey": SITEKEY, "url": URL, "version": "v2", "enterprise": 1, "invisible": 0}]
    assert pages.evaluated == [("t1", "detect"), ("t1", "inject"), ("t2", "detect")]
    assert any("solved t1" in m for m, _ in w._logs)
    assert TOKEN not in json.dumps(w._logs)  # token never logged (RULE 20)
    assert w._statuses and w._statuses[-1]["solved_total"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attempt_budget_per_tab_resets_when_challenge_clears():
    sdk = FakeSdk(exc=RuntimeError("ERROR_ZERO_BALANCE"))
    state = {"visible": True}
    pages = FakePages({"t1": lambda: detect_payload(visible=state["visible"])})
    w = make_watcher(pages, [{"id": "t1", "url": URL}], sdk=sdk)
    for _ in range(MAX_SOLVE_ATTEMPTS + 2):
        await w.tick()
    assert len(sdk.calls) == MAX_SOLVE_ATTEMPTS  # budget exhausted → no more paid tasks
    assert w.status()["failed_total"] == MAX_SOLVE_ATTEMPTS
    assert "ERROR_ZERO_BALANCE" in w.status()["last_error"]
    state["visible"] = False
    await w.tick()  # challenge gone → budget reset
    state["visible"] = True
    await w.tick()
    assert len(sdk.calls) == MAX_SOLVE_ATTEMPTS + 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inject_failure_counts_as_failed_not_solved():
    pages = FakePages({"t1": detect_payload()}, inject_ok=False)
    w = make_watcher(pages, [{"id": "t1", "url": URL}])
    await w.tick()
    st = w.status()
    assert st["solved_total"] == 0 and st["failed_total"] == 1
    assert st["last_error"].startswith("inject failed")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsolvable_kind_and_no_key_never_call_sdk():
    sdk = FakeSdk()
    pages = FakePages({"t1": detect_payload(kind="hcaptcha", sitekey="h")})
    w = make_watcher(pages, [{"id": "t1", "url": URL}], sdk=sdk)
    await w.tick()
    assert sdk.calls == [] and any("not SDK-solvable" in m for m, _ in w._logs)
    w2 = make_watcher(FakePages({"t1": detect_payload()}), [{"id": "t1", "url": URL}], sdk=sdk, key="")
    await w2.tick()
    assert sdk.calls == [] and w2.status()["last_error"] == "no 2Captcha API key"
    assert w2.status()["has_key"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eval_errors_and_timeouts_fail_open(monkeypatch):
    import app.services.captcha_watcher.watcher as wmod

    async def boom(tab_id, js):
        raise RuntimeError("tab closed")

    deps = WatcherDeps(tabs=lambda: [{"id": "t1", "url": URL}], evaluate=boom,
                       solver_factory=lambda: None)
    w = CaptchaWatcher(deps)
    assert await w.tick() == 1
    assert "tab closed" in w.status()["last_error"]

    monkeypatch.setattr(wmod, "EVAL_TIMEOUT_SEC", 0.01)

    async def hang(tab_id, js):
        await asyncio.sleep(1)

    w2 = CaptchaWatcher(WatcherDeps(tabs=lambda: [SimpleNamespace(tab_id="t9", url=URL)],
                                    evaluate=hang, solver_factory=lambda: None))
    assert await w2.tick() == 1
    assert w2.status()["failed_total"] == 0  # a hung tab is not a failed solve


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tabs_provider_may_be_async_and_broken_tabs_are_skipped():
    async def tabs():
        return [{"id": "", "url": URL}, {"id": "t1", "url": URL}]

    pages = FakePages({"t1": detect_payload(visible=False)})
    deps = WatcherDeps(tabs=tabs, evaluate=pages.evaluate, solver_factory=lambda: None)
    assert await CaptchaWatcher(deps).tick() == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_forever_and_stop_lifecycle():
    pages = FakePages({"t1": detect_payload(visible=False)})
    w = make_watcher(pages, [{"id": "t1", "url": URL}])
    task = asyncio.get_running_loop().create_task(w.run_forever())
    await asyncio.sleep(0.05)
    assert w.running and w.status()["running"] is True and w.status()["ticks"] >= 1
    w.stop()
    await asyncio.wait_for(task, timeout=2)
    assert not w.running and w._statuses[-1]["running"] is False
    assert any("Captcha Watcher ON" in m for m, _ in w._logs)
    assert any("Captcha Watcher OFF" in m for m, _ in w._logs)
    w.stop()  # idempotent after exit


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tick_exception_is_logged_not_fatal():
    def bad_tabs():
        raise RuntimeError("pool gone")

    w = CaptchaWatcher(WatcherDeps(tabs=bad_tabs, evaluate=None, solver_factory=lambda: None))
    await w._safe_tick()
    assert "pool gone" in w.status()["last_error"]


@pytest.mark.unit
def test_status_and_result_types_are_log_safe():
    st = WatcherStatus()
    st.touch()
    d = st.to_dict()
    assert d["running"] is False and d["last_tick_at"] > 0 and "balance" in d
    r = SolveResult(ok=True, token=TOKEN, task_id="1", elapsed_s=3.14159)
    assert r.masked() == {"ok": True, "task_id": "1", "error": "", "elapsed_s": 3.1, "token_len": len(TOKEN)}
