"""CaptchaSolver — per-tab inflight dedup, poll loop, inject+verify, RULE 7 stop.

RULE 8: real solver against fake CDP + fake 2Captcha client (no network).
The FakeClock steps time per `monotonic()` read so poll/verify deadlines are
deterministic without real sleeps.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.services.captcha.solver as solver_mod
from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings
from app.services.captcha.signals import CaptchaSignal
from app.services.captcha.stats import CaptchaStatsStore

SITEKEY = "6Lsitekey00000000000000000000"
URL = "https://arena.ai/image/direct"


def detect_result(kind="recaptcha_enterprise", sitekey=SITEKEY, url=URL):
    """Probe-shaped result (note: the probe uses the 'url' key)."""
    return {"visible": True, "kind": kind, "sitekey": sitekey, "url": url}


def signal(kind="recaptcha_enterprise", sitekey=SITEKEY, url=URL, is_invisible=False):
    return CaptchaSignal(visible=True, kind=kind, sitekey=sitekey, page_url=url,
                         is_invisible=is_invisible)


class FakeClock:
    """Advances `step` seconds on every monotonic() read (0 = frozen)."""

    def __init__(self, step=0.0):
        self.t = 1000.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


class FakeCtrl:
    """CDP double: dispatches probes by JS content, dialog flag by sequence."""

    def __init__(self, visible_seq, inject_results=None, close_results=None, visible_default=False):
        self._visible = list(visible_seq)
        self._visible_default = visible_default
        self._inject = list(inject_results if inject_results is not None else [True])
        self._close = list(close_results if close_results is not None else [{"ok": True, "used": "none"}])
        self.probes = []
        self.overlay_calls = []
        self.cdp = SimpleNamespace(evaluate=self._evaluate)

    async def _evaluate(self, js):
        self.probes.append(js)
        if "Security Verification" in js:  # detect probe (unique marker)
            return json.dumps(detect_result())
        if "g-recaptcha-response" in js:  # inject probe
            ok = self._inject.pop(0) if self._inject else False
            return json.dumps({"ok": ok, "scope": "dialog", "tag": "TEXTAREA"})
        # close-dialog steps (one full function source per call; the step arg is the tail)
        if js.endswith('("esc")') or js.endswith('("close")') or js.endswith('("nuclear")'):
            r = self._close.pop(0) if self._close else {"ok": True, "used": "nuclear", "removed": 1}
            return json.dumps(r)
        return json.dumps({"ok": True, "used": "submit"})  # continue probe

    async def is_security_dialog_visible(self):
        return self._visible.pop(0) if self._visible else self._visible_default

    async def show_watcher_overlay(self, *a, **k):
        self.overlay_calls.append(k)
        return True

    async def hide_watcher_overlay(self):
        return True


class FakeClient:
    def __init__(self, key, timeout_sec=30.0, results=None, exc=None):
        self.key = key
        self.created = []
        self.deleted = []
        self._results = list(results or [])
        self._exc = exc
        self.closed = False
        self._count = 100

    async def create_task(self, task):
        self.created.append(task)
        self._count += 1
        return str(self._count)

    async def get_result(self, task_id):
        if self._exc is not None:
            raise self._exc
        if self._results:
            return self._results.pop(0)
        return {"errorId": 0, "status": "processing"}

    async def delete_task(self, task_id):
        self.deleted.append(task_id)
        return True

    async def aclose(self):
        self.closed = True


def make_env(monkeypatch, isolated_config_dir, client, step=0.0):
    """Real key store/stats/solver wired to a fake client + fake clock."""
    keys = CaptchaKeyStore(isolated_config_dir)
    stats = CaptchaStatsStore(isolated_config_dir)
    logs = []
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)
    monkeypatch.setattr(solver_mod.time, "monotonic", FakeClock(step))

    async def instant_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)
    solver = solver_mod.CaptchaSolver(keys, stats, lambda m, l="info": logs.append((m, l)))
    return solver, stats, logs, client


@pytest.mark.unit
@pytest.mark.asyncio
async def test_success_path_records_solved(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "processing"},
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = FakeCtrl(visible_seq=[True, False])  # verify loop: still visible, then gone
    outcome = await solver.solve(ctrl, "tabA", signal(), lambda: False)
    assert outcome.status == "solved"
    assert outcome.method == "auto"
    assert outcome.task_id == "101"
    assert any("createTask OK → task 101" in m and "sitekey=" in m for m, _ in logs)  # API trace
    assert any("token received (task 101" in m for m, _ in logs)  # API trace
    # docs-exact enterprise payload (2026-09-18 detection research)
    assert client.created == [{"type": "RecaptchaV2EnterpriseTaskProxyless",
                               "websiteURL": URL, "websiteKey": SITEKEY,
                               "isInvisible": False}]
    assert client.deleted == []
    d = stats.to_dict()
    assert d["auto_solved"] == 1 and d["tasks_created"] == 1
    assert any("token accepted" in m for m, _ in logs)
    assert client.closed  # session hygiene


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v2_kind_maps_to_v2_task_type(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = FakeCtrl(visible_seq=[False])  # verify loop sees it gone on first check
    outcome = await solver.solve(ctrl, "t", signal(kind="recaptcha_v2", sitekey="6Lv2key"),
                                 lambda: False)
    assert outcome.status == "solved"
    assert client.created[0]["type"] == "RecaptchaV2TaskProxyless"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_error_falls_back_and_deletes_task(monkeypatch, isolated_config_dir):
    from app.services.captcha.api_client import ApiError
    client = FakeClient("K", exc=ApiError("no_credit", error_id=3))
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = FakeCtrl(visible_seq=[])
    outcome = await solver.solve(ctrl, "tabB", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "no_credit" in outcome.reason
    assert any("getTaskResult FAILED" in m and "errorId=3" in m for m, _ in logs)  # raw API error visible
    assert client.deleted  # credit freed
    assert stats.to_dict()["auto_failed"] == 1
    assert stats.last_error == "no_credit"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_mid_poll_returns_failed_and_deletes(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[{"errorId": 0, "status": "processing"}])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = FakeCtrl(visible_seq=[])

    def stop():
        return True

    outcome = await solver.solve(ctrl, "t", signal(), stop)
    assert outcome.status == "auto_failed"
    assert "stopped" in outcome.reason
    assert client.deleted  # credit freed on stop
    assert stats.to_dict()["auto_failed"] == 0  # stop is not a solve failure
    assert any("stopped" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timeout_returns_failed(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[{"errorId": 0, "status": "processing"}])
    solver, stats, _, _ = make_env(monkeypatch, isolated_config_dir, client, step=31)
    ctrl = FakeCtrl(visible_seq=[])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert stats.last_error == "poll_timeout"
    assert client.deleted


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inject_failure_falls_back(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, _, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = FakeCtrl(visible_seq=[], inject_results=[False])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "inject" in outcome.reason
    assert stats.to_dict()["auto_failed"] == 1
    assert client.deleted


@pytest.mark.unit
@pytest.mark.asyncio
async def test_token_not_accepted_falls_back(monkeypatch, isolated_config_dir):
    """Dialog survives grace AND all three force-close steps → not_accepted."""
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, _, _ = make_env(monkeypatch, isolated_config_dir, client, step=21)
    ctrl = FakeCtrl(visible_seq=[], visible_default=True,
                    close_results=[{"ok": False, "reason": "no close control found"}] * 3)
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "not_accepted" in outcome.reason
    assert "no callback in dialog anchor" in outcome.reason  # reason is specific, not opaque
    assert client.deleted


@pytest.mark.unit
@pytest.mark.asyncio
async def test_force_close_rescues_stuck_dialog(monkeypatch, isolated_config_dir):
    """Completion fix: dialog can't self-close on an injected token — Escape does."""
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=21)
    # grace final check True; after esc the dialog is gone; second verify gone
    ctrl = FakeCtrl(visible_seq=[True, False, False], visible_default=True,
                    close_results=[{"ok": True, "used": "esc"}])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "solved"
    assert any("force-closed (esc)" in m for m, _ in logs)
    assert client.deleted == []  # token was consumed — no credit refund


@pytest.mark.unit
@pytest.mark.asyncio
async def test_force_close_nuclear_after_failed_steps(monkeypatch, isolated_config_dir):
    """esc + close fail (no control), nuclear removes the dialog → solved."""
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=21)
    close_results = [{"ok": True, "used": "esc"},
                     {"ok": True, "used": "close-btn"},
                     {"ok": True, "used": "nuclear", "removed": 3}]
    # grace final True; after esc True; after close True; after nuclear gone; second verify gone
    ctrl = FakeCtrl(visible_seq=[True, True, True, False, False], close_results=close_results)
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "solved"
    assert any("force-closed (nuclear)" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_force_close_already_closed(monkeypatch, isolated_config_dir):
    """Close probe reports the dialog already gone → no removal, solved."""
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=21)
    ctrl = FakeCtrl(visible_seq=[True, False], close_results=[{"ok": True, "used": "none"}])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "solved"
    assert any("force-closed (already-closed)" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_token_not_accepted_callback_called(monkeypatch, isolated_config_dir):
    """cb invoked but dialog persists → server-side rejection signature."""
    import json

    class CbCtrl(FakeCtrl):
        async def _evaluate(self, js):
            if "g-recaptcha-response" in js:
                return json.dumps({"ok": True, "scope": "dialog", "tag": "TEXTAREA",
                                   "cb": "abc123", "cbCalled": True})
            return await super()._evaluate(js)

    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=21)
    ctrl = CbCtrl(visible_seq=[], visible_default=True,
                  close_results=[{"ok": False, "reason": "no close control found"}] * 3)
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "callback called" in outcome.reason
    assert any("cb=called abc123" in m for m, _ in logs)  # inject detail logged


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inflight_dedup_same_tab_single_task(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "processing"},
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = FakeCtrl(visible_seq=[True, False])
    a, b = await asyncio.gather(
        solver.solve(ctrl, "same-tab", signal(), lambda: False),
        solver.solve(ctrl, "same-tab", signal(), lambda: False),
    )
    assert a.status == "solved" and b.status == "solved"
    assert len(client.created) == 1  # one 2Captcha task for two racing callers


@pytest.mark.unit
@pytest.mark.asyncio
async def test_different_tabs_solve_in_parallel(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "T1"}},
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "T2"}},
    ])
    solver, stats, _, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl_a = FakeCtrl(visible_seq=[False])
    ctrl_b = FakeCtrl(visible_seq=[False])
    a, b = await asyncio.gather(
        solver.solve(ctrl_a, "tabA", signal(), lambda: False),
        solver.solve(ctrl_b, "tabB", signal(), lambda: False),
    )
    assert a.status == "solved" and b.status == "solved"
    assert len(client.created) == 2  # independent tasks per page (multi-tasking)
    assert stats.to_dict()["auto_solved"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_key_never_calls_api(monkeypatch, isolated_config_dir):
    client = FakeClient("K")
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client)
    solver._keys = CaptchaKeyStore(isolated_config_dir / "empty")  # dir without a key file
    ctrl = FakeCtrl(visible_seq=[])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "no_key" in outcome.reason
    assert client.created == []

@pytest.mark.unit
@pytest.mark.asyncio
async def test_payload_exact_format_and_isinvisible_only_enterprise(monkeypatch, isolated_config_dir):
    """Docs-exact createTask payload: isInvisible is an ENTERPRISE field only."""
    ready = {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}}
    client = FakeClient("K", results=[ready, ready])
    solver, _, _, client = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = FakeCtrl(visible_seq=[False, False], inject_results=[True, True])

    ent = await solver.solve(ctrl, "t-ent", signal(is_invisible=True), lambda: False)
    v2 = await solver.solve(ctrl, "t-v2", signal(kind="recaptcha_v2"), lambda: False)
    assert ent.status == "solved" and v2.status == "solved"
    t_ent, t_v2 = client.created
    assert t_ent["type"] == "RecaptchaV2EnterpriseTaskProxyless"
    assert t_ent["websiteURL"] == URL and t_ent["websiteKey"] == SITEKEY
    assert t_ent["isInvisible"] is True
    assert t_v2["type"] == "RecaptchaV2TaskProxyless"
    assert "isInvisible" not in t_v2  # not a v2 field per 2Captcha docs
