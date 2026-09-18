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

    def __init__(self, visible_seq, inject_results=None):
        self._visible = list(visible_seq)
        self._inject = list(inject_results if inject_results is not None else [True])
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
        return json.dumps({"ok": True, "used": "submit"})  # continue probe

    async def is_security_dialog_visible(self):
        return self._visible.pop(0) if self._visible else False

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
    ctrl = FakeCtrl(visible_seq=[True, True, False])  # pre-inject up; verify: up, then gone
    outcome = await solver.solve(ctrl, "tabA", signal(), lambda: False)
    assert outcome.status == "solved"
    assert outcome.method == "auto"
    assert outcome.task_id == "101"
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
    solver, stats, _, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = FakeCtrl(visible_seq=[])
    outcome = await solver.solve(ctrl, "tabB", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "no_credit" in outcome.reason
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
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, _, _ = make_env(monkeypatch, isolated_config_dir, client, step=21)
    ctrl = FakeCtrl(visible_seq=[True, True])  # pre-inject up; dialog never closes after
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "not_accepted" in outcome.reason
    assert "no site callback found" in outcome.reason  # reason is specific, not opaque
    assert client.deleted


@pytest.mark.unit
@pytest.mark.asyncio
async def test_token_not_accepted_callback_called(monkeypatch, isolated_config_dir):
    """cb invoked but dialog persists → server-side rejection signature."""
    import json

    class CbCtrl(FakeCtrl):
        async def _evaluate(self, js):
            if "g-recaptcha-response" in js:
                return json.dumps({"ok": True, "scope": "dialog", "fields": 2,
                                   "cb": "abc123", "cbCalled": True,
                                   "cbSource": "anchor-cb:abc123", "clientsSeen": 0})
            return await super()._evaluate(js)

    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=21)
    ctrl = CbCtrl(visible_seq=[True, True])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "callback called via anchor-cb:abc123" in outcome.reason
    assert any("cb=called abc123 via anchor-cb:abc123" in m for m, _ in logs)  # inject detail logged
    assert any("fields=2" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_token_not_accepted_data_callback_source(monkeypatch, isolated_config_dir):
    """data-callback invoked but dialog persists → reason names the source."""

    class DcCtrl(FakeCtrl):
        async def _evaluate(self, js):
            if "g-recaptcha-response" in js:
                return json.dumps({"ok": True, "scope": "dialog", "fields": 1,
                                   "cb": "onArenaSolve", "cbCalled": True,
                                   "cbSource": "data-callback:onArenaSolve"})
            return await super()._evaluate(js)

    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=21)
    ctrl = DcCtrl(visible_seq=[True, True])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "callback called via data-callback:onArenaSolve" in outcome.reason
    assert any("via data-callback:onArenaSolve" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inject_probe_receives_sitekey(monkeypatch, isolated_config_dir):
    """The dialog sitekey travels into the probe for the cfg-client search."""
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = FakeCtrl(visible_seq=[False])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "solved"
    inject_js = [p for p in ctrl.probes if "g-recaptcha-response" in p]
    assert len(inject_js) == 1
    assert SITEKEY in inject_js[0]  # sitekey steers the client search


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inflight_dedup_same_tab_single_task(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "processing"},
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = FakeCtrl(visible_seq=[True, True, False])
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


@pytest.mark.unit
def test_token_fingerprint_shapes():
    fp = solver_mod._token_fingerprint
    assert fp("") == "EMPTY" and fp(None) == "EMPTY"
    assert fp("TOK") == "SUSPICIOUS len=3"
    assert fp("03AGdB25" + "y" * 500 + "xQ12") == "len=512 head=03AGdB25 tail=xQ12"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_logs_task_id_and_token_evidence(monkeypatch, isolated_config_dir):
    token = "03AGdB25" + "y" * 500 + "xQ12"
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": token}},
    ])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    outcome = await solver.solve(FakeCtrl(visible_seq=[False]), "t", signal(), lambda: False)
    assert outcome.status == "solved"
    assert any("#101 submitted" in m for m, _ in logs)
    assert any("token received in " in m and "len=512" in m for m, _ in logs)
    assert any("head=03AGdB25" in m and "tail=xQ12" in m for m, _ in logs)
    assert token not in "\n".join(m for m, _ in logs)  # RULE 20: never the token


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_on_slow_poll(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "processing"},
        {"errorId": 0, "status": "processing"},
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=20)
    solver._keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=300))
    outcome = await solver.solve(FakeCtrl(visible_seq=[False]), "t", signal(), lambda: False)
    assert outcome.status == "solved"
    assert any("still processing" in m and "elapsed" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_preinject_states_logged(monkeypatch, isolated_config_dir):
    ready = {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}}
    client = FakeClient("K", results=[ready, ready])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = FakeCtrl(visible_seq=[True, True, False], inject_results=[True, True])
    assert (await solver.solve(ctrl, "t1", signal(), lambda: False)).status == "solved"
    assert any("dialog still visible — injecting" in m for m, _ in logs)
    ctrl2 = FakeCtrl(visible_seq=[False])
    assert (await solver.solve(ctrl2, "t2", signal(), lambda: False)).status == "solved"
    assert any("already gone" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_status_surfaces_provider_detail(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "failed", "errorCode": "ERROR_TASK_ABSENT",
         "errorDescription": "Task property is missing"},
    ])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    outcome = await solver.solve(FakeCtrl(visible_seq=[]), "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert outcome.reason.startswith("task_failed")  # prefix stable
    assert stats.last_error == "ERROR_TASK_ABSENT"
    assert any("task_failed (ERROR_TASK_ABSENT)" in m for m, _ in logs)
    assert client.deleted


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_status_without_detail_keeps_bare_reason(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[{"errorId": 0, "status": "failed"}])
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    outcome = await solver.solve(FakeCtrl(visible_seq=[]), "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert outcome.reason.startswith("task_failed")
    assert stats.last_error == "task_failed"
    assert any(m.endswith("poll ended: task_failed") for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_error_surfaces_provider_code(monkeypatch, isolated_config_dir):
    from app.services.captcha.api_client import ApiError
    client = FakeClient("K", exc=ApiError("task_error", message="ERROR_ZERO_BALANCE"))
    solver, stats, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    outcome = await solver.solve(FakeCtrl(visible_seq=[]), "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert "task_error" in outcome.reason
    assert stats.last_error == "ERROR_ZERO_BALANCE"
    assert any("task_error (ERROR_ZERO_BALANCE)" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_solved_line_splits_token_time(monkeypatch, isolated_config_dir):
    import re
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "processing"},
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = FakeCtrl(visible_seq=[True, True, False])
    assert (await solver.solve(ctrl, "t", signal(), lambda: False)).status == "solved"
    assert any(re.search(r"in \d+s \(token \d+s, token accepted\)", m) for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_abandoned_task_deletion_logged(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[{"errorId": 0, "status": "processing"}])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=31)
    outcome = await solver.solve(FakeCtrl(visible_seq=[]), "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert any("#101 deleted (credit freed)" in m for m, _ in logs)


class WatchCtrl(FakeCtrl):
    """FakeCtrl + scripted page-error corpora per poll."""

    def __init__(self, corpora, **kw):
        super().__init__(**kw)
        self._corpora = list(corpora)

    async def scan_page_errors(self):
        if len(self._corpora) > 1:
            return self._corpora.pop(0)
        return self._corpora[0] if self._corpora else ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_logs_isinvisible_flag(monkeypatch, isolated_config_dir):
    ready = {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}}
    client = FakeClient("K", results=[ready, ready])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    await solver.solve(FakeCtrl(visible_seq=[False]), "t1", signal(is_invisible=True), lambda: False)
    await solver.solve(FakeCtrl(visible_seq=[False]), "t2", signal(is_invisible=False), lambda: False)
    assert any("isInvisible=True" in m for m, _ in logs)
    assert any("isInvisible=False" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mid_solve_page_error_timestamped(monkeypatch, isolated_config_dir):
    processing = {"errorId": 0, "status": "processing"}
    ready = {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}}
    client = FakeClient("K", results=[processing, processing, processing, ready])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = WatchCtrl(corpora=["", "", "Something went wrong while generating the response. Trace ID: 1"],
                     visible_seq=[False])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "page_error"
    assert outcome.token_fp == ""
    assert any("appeared during solve (" in m and "Something went wrong" in m for m, _ in logs)
    assert client.deleted  # page failure makes the provider task stale


@pytest.mark.unit
@pytest.mark.asyncio
async def test_preexisting_page_error_stays_silent(monkeypatch, isolated_config_dir):
    processing = {"errorId": 0, "status": "processing"}
    ready = {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}}
    client = FakeClient("K", results=[processing, processing, ready])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client)
    banner = "Something went wrong while generating the response. Trace ID: 1"
    ctrl = WatchCtrl(corpora=[banner, banner], visible_seq=[False])
    assert (await solver.solve(ctrl, "t", signal(), lambda: False)).status == "solved"
    assert not any("appeared during solve" in m for m, _ in logs)  # stale at solve start


@pytest.mark.unit
@pytest.mark.asyncio
async def test_outcome_carries_report_lifecycle(monkeypatch, isolated_config_dir):
    token = "03AGdB25" + "y" * 500 + "xQ12"
    processing = {"errorId": 0, "status": "processing"}
    ready = {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": token}}
    client = FakeClient("K", results=[processing, processing, ready])
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    outcome = await solver.solve(FakeCtrl(visible_seq=[True, True, False]), "t", signal(), lambda: False)
    assert outcome.status == "solved"
    assert outcome.polls == 3
    assert outcome.token_fp == "len=512 head=03AGdB25 tail=xQ12"
    assert outcome.token_sec > 0
    assert outcome.dialog_at_token == "visible"
    assert "scope=dialog" in outcome.inject and "fields=1" in outcome.inject
    assert outcome.page_error == "" and outcome.page_error_at_s == 0.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_outcome_carries_attempt_evidence(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[{"errorId": 0, "status": "processing"}])
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client, step=31)
    outcome = await solver.solve(FakeCtrl(visible_seq=[]), "t", signal(), lambda: False)
    assert outcome.status == "auto_failed"
    assert outcome.polls >= 1  # retry count survives the failure
    assert outcome.token_fp == "" and outcome.dialog_at_token == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_outcome_carries_mid_solve_page_error(monkeypatch, isolated_config_dir):
    ready = {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}}
    processing = {"errorId": 0, "status": "processing"}
    client = FakeClient("K", results=[processing, processing, ready])
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client)
    ctrl = WatchCtrl(corpora=["", "Something went wrong. Trace ID: 7"], visible_seq=[False])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "page_error"
    assert "Something went wrong" in outcome.page_error
    assert outcome.page_error_at_s >= 0.0
    assert client.deleted  # late token is never injected after page failure


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stale_token_refuses_injection_and_deletes_task(monkeypatch, isolated_config_dir):
    """Pass-path guard: a token older than Google's single-use ~2-minute window
    is never injected (docs/archive/2026-09-18-captcha-pass-path/design.md §5 G-3).
    FakeClock(step=150) puts 150 s between token receipt and the inject check."""
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=150)
    ctrl = FakeCtrl(visible_seq=[True, True, False])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "token_stale"
    assert "single-use" in outcome.reason
    assert client.deleted == ["101"]  # credit freed, not billed for a dead token
    assert ctrl.probes == []          # injection never attempted
    assert any("token age" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fresh_token_passes_staleness_guard(monkeypatch, isolated_config_dir):
    """The guard must never fire on a normal solve (age seconds, not minutes)."""
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, _, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = FakeCtrl(visible_seq=[True, False])
    outcome = await solver.solve(ctrl, "t", signal(), lambda: False)
    assert outcome.status == "solved"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_challenge_active_logs_escalation(monkeypatch, isolated_config_dir):
    """bframe image-grid escalation is reported, solving behavior unchanged."""
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = FakeCtrl(visible_seq=[True, False])
    sig = signal()
    sig.challenge_active = True
    outcome = await solver.solve(ctrl, "t", sig, lambda: False)
    assert outcome.status == "solved"  # same path, same acceptance gate
    assert any("image-challenge escalation" in m for m, _ in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_escalation_line_when_challenge_inactive(monkeypatch, isolated_config_dir):
    client = FakeClient("K", results=[
        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
    ])
    solver, _, logs, _ = make_env(monkeypatch, isolated_config_dir, client, step=5)
    ctrl = FakeCtrl(visible_seq=[True, False])
    assert (await solver.solve(ctrl, "t", signal(), lambda: False)).status == "solved"
    assert not any("image-challenge escalation" in m for m, _ in logs)
