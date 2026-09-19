"""D2/F-B: bounded token-free milestones — unit + synthetic-session golden (RULE 8)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.captcha.signals import SolveOutcome
from app.services.captcha_recording.milestones import (
    MAX_FIELD_CHARS, MILESTONE_PHASES, assert_token_free, build_milestone,
)
from app.services.captcha_recording.reader import EvidenceReader
from app.services.captcha_recording.sanitize import contains_tokenish
from app.services.captcha_recording.recorder import CaptchaRecorder
from app.services.captcha_recording.models import RecordingLimits
from app.services.captcha_recording.store import RecordingStore

LONG_TOKEN = "A" * 100


@pytest.mark.unit
def test_build_milestone_whitelists_and_bounds_fields():
    outcome = SolveOutcome(status="solved", reason="token accepted", method="auto",
                           task_id="42", polls=3, attempts=2, token_sec=12.5,
                           token_fp="len=512 head=03AGdB25 tail=xQ12",
                           dialog_at_token="visible",
                           inject="scope=dialog fields=2 cb=called x via anchor",
                           continue_result="clicked", page_error_at_s=0.0,
                           page_error="", page_identity="page-1",
                           challenge_identity="challenge-1",
                           task_created_sec=0.4, dialog_cleared_sec=18.2)
    payload = build_milestone("final", outcome, offset_ms=20000)
    assert payload["phase"] == "final" and payload["offset_ms"] == 20000
    assert payload["task_id"] == "42" and payload["polls"] == 3
    assert payload["token_sec_ms"] == 12500  # seconds fields become ms
    assert payload["dialog_cleared_sec_ms"] == 18200
    assert payload["page_identity"] == "page-1"
    assert payload["continue_result"] == "clicked"
    for value in payload.values():  # size bound on every string field
        if isinstance(value, str):
            assert len(value) <= MAX_FIELD_CHARS


@pytest.mark.unit
def test_build_milestone_drops_unselected_and_empty_fields():
    long_reason = ("dialog still visible after token injection (no site callback found) " * 8)
    outcome = SolveOutcome(task_id="7", reason=long_reason)
    payload = build_milestone("auto_finished", outcome, offset_ms=5)
    assert payload["task_id"] == "7"
    assert len(payload["reason"]) == MAX_FIELD_CHARS  # bounded, not dropped
    assert "token_fp" not in payload  # not in this phase's whitelist
    assert "page_error" not in payload  # empty values are omitted


@pytest.mark.unit
def test_build_milestone_rejects_unknown_phase():
    with pytest.raises(ValueError):
        build_milestone("nope", SolveOutcome(), offset_ms=1)
    assert MILESTONE_PHASES  # phases are an explicit closed set


@pytest.mark.unit
def test_assert_token_free_raises_on_credential_shapes():
    assert_token_free({"reason": "token accepted"})  # clean evidence passes
    with pytest.raises(ValueError):
        assert_token_free({"reason": "token accepted", "task_id": LONG_TOKEN})
    with pytest.raises(ValueError):
        assert_token_free({"inject": "scope=dialog cb=bearer " + LONG_TOKEN})


@pytest.mark.unit
def test_contains_tokenish_shapes():
    assert contains_tokenish("A" * 80)
    assert contains_tokenish("Bearer abc.def")
    assert not contains_tokenish("len=512 head=03AGdB25 tail=xQ12")  # fingerprint is safe
    assert not contains_tokenish("scope=dialog fields=2")


class FakeRecordingCDP:
    def __init__(self):
        self.events = SimpleNamespace(add=lambda cb: None, remove=lambda cb: None)
        self.sent = []

    async def evaluate(self, script):
        if "queue.splice" in script:
            return {"ok": True, "changes": [], "dropped": 0}
        if "cloneNode" in script:
            return {"ok": True, "url": "https://arena.ai/c/1", "title": "Arena",
                    "viewport": {"w": 100, "h": 100}, "html": "<html><main>state</main></html>"}
        return {"ok": True}

    async def send(self, method, params, timeout=5):
        self.sent.append((method, params, timeout))
        return {"result": {}}


def _outcome(**overrides):
    base = dict(status="solved", method="auto", task_id="42", polls=3, attempts=2,
                reason="token accepted", token_sec=12.5, token_fp="len=512 head=03AGdB25 tail=xQ12",
                dialog_at_token="visible", inject="scope=dialog fields=1 cb=called via anchor",
                continue_result="clicked", page_identity="page-1", challenge_identity="c-1",
                task_created_sec=0.4, dialog_cleared_sec=18.2)
    base.update(overrides)
    return SolveOutcome(**base)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_synthetic_session_golden_persists_milestones(tmp_path):
    """D2 golden: task_created → token_ready → auto_finished → final, bounded + token-free."""
    cdp = FakeRecordingCDP()
    ctrl = SimpleNamespace(cdp=cdp)
    limits = RecordingLimits(poll_interval_sec=0.01, checkpoint_interval_sec=0,
                             max_events=100, max_snapshots=5)
    recorder = CaptchaRecorder(
        RecordingStore(tmp_path), ctrl,
        {"eid": "e-golden", "tab": "t1", "url": "https://arena.ai/c/1",
         "source": "test", "kind": "recaptcha_enterprise"}, limits)
    await recorder.start()
    await recorder.note_outcome("task_created", _outcome())
    await recorder.note_outcome("token_ready", _outcome())
    await recorder.note_outcome("auto_attempt_finished", _outcome())
    result = await recorder.finish(_outcome())

    folder = recorder.store.session_folder(recorder.session_id)
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
    phases = [e["phase"] for e in events if e["kind"] == "milestone"]
    assert phases == ["task_created", "token_ready", "auto_finished", "final"]
    assert all(0 <= e["offset_ms"] for e in events if e["kind"] == "milestone")
    assert result["dropped_events"] == 0

    details = EvidenceReader(recorder.store.root).details(recorder.session_id)
    assert [m["phase"] for m in details["milestones"]] == phases  # reader surfaces them
    blob = (folder / "events.jsonl").read_text()
    assert not contains_tokenish(blob)  # I-29/I-32: no raw token can be written
    for event in events:
        if event["kind"] == "milestone":
            assert all(len(v) <= MAX_FIELD_CHARS for v in event.values() if isinstance(v, str))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milestone_fail_closed_on_token_smuggling(tmp_path):
    """A raw token in outcome evidence yields no milestone, only a skip marker."""
    cdp = FakeRecordingCDP()
    ctrl = SimpleNamespace(cdp=cdp)
    recorder = CaptchaRecorder(
        RecordingStore(tmp_path), ctrl,
        {"eid": "e-tok", "tab": "t2", "url": "https://arena.ai/c/1",
         "source": "test", "kind": "recaptcha_enterprise"},
        RecordingLimits(poll_interval_sec=0.01, checkpoint_interval_sec=0,
                        max_events=100, max_snapshots=5))
    await recorder.start()
    await recorder.note_outcome("auto_attempt_finished",
                                _outcome(reason="accepted " + LONG_TOKEN,
                                         task_id="42", inject="scope=dialog cb=ok"))
    await recorder.finish(_outcome(task_id=LONG_TOKEN, reason="token accepted"))
    folder = recorder.store.session_folder(recorder.session_id)
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
    assert not any(e["kind"] == "milestone" for e in events)  # fail closed: nothing half-written
    assert any(e["kind"] == "milestone_skipped" for e in events)
    assert LONG_TOKEN not in (folder / "events.jsonl").read_text()


# --- solver milestone hook (D2) ---

import app.services.captcha.solver as solver_mod
from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings


class HookClock:
    def __init__(self, step=0.0):
        self.t = 1000.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


class HookCtrl:
    """Minimal CDP double: dialog visible→gone, inject ok with a site callback."""

    def __init__(self):
        self._visible = iter([True, True, True, False])
        self.cdp = SimpleNamespace(evaluate=self._evaluate)

    async def _evaluate(self, js):
        if "g-recaptcha-response" in js:
            return json.dumps({"ok": True, "scope": "dialog", "fields": 1,
                               "cb": "onArenaSolve", "cbCalled": True,
                               "cbSource": "data-callback:onArenaSolve"})
        return json.dumps({"ok": True})

    async def is_security_dialog_visible(self):
        try:
            return next(self._visible)
        except StopIteration:
            return False


class HookClient:
    def __init__(self, key, timeout_sec=30.0):
        self.created, self.deleted, self.closed = [], [], False
        self._n = 100

    async def create_task(self, task):
        self.created.append(task)
        self._n += 1
        return str(self._n)

    async def get_result(self, task_id):
        return {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}}

    async def delete_task(self, task_id):
        self.deleted.append(task_id)
        return True

    async def aclose(self):
        self.closed = True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_solver_fires_milestones_in_order(monkeypatch, isolated_config_dir):
    seen = []

    async def hook(tab_id, phase, outcome):
        seen.append((tab_id, phase, outcome))

    client = HookClient("K")
    keys = CaptchaKeyStore(isolated_config_dir)
    from app.services.captcha.stats import CaptchaStatsStore
    keys.save(CaptchaSettings(enabled=True, api_key="K" * 16, solve_timeout_sec=30))
    monkeypatch.setattr(solver_mod, "Captcha2Client", lambda key, timeout_sec=30.0: client)
    monkeypatch.setattr(solver_mod.time, "monotonic", HookClock(step=5))

    async def instant_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)
    sig = solver_mod.CaptchaSignal(visible=True, kind="recaptcha_v2", sitekey="6Lv2key",
                                   page_url="https://arena.ai/c/1",
                                   page_identity="page-1", challenge_identity="c-1")
    solver = solver_mod.CaptchaSolver(keys, CaptchaStatsStore(isolated_config_dir),
                                      lambda m, l="info": None, milestone_hook=hook)
    outcome = await solver.solve(HookCtrl(), "tab-hook", sig, lambda: False)
    assert outcome.status == "solved"

    phases = [phase for _, phase, _ in seen]
    assert phases == ["task_created", "token_ready", "injected",
                      "acceptance_candidate", "dialog_cleared"]
    assert all(tab == "tab-hook" for tab, _, _ in seen)
    _, _, created_evidence = seen[0]
    assert created_evidence.task_id == "101" and created_evidence.page_identity == "page-1"
    from dataclasses import asdict
    blob = json.dumps([asdict(e) for _, _, e in seen])
    assert not contains_tokenish(blob)  # hook payloads are token-free by construction
    assert outcome.continue_result == "clicked"
    assert outcome.dialog_cleared_sec >= outcome.token_sec
