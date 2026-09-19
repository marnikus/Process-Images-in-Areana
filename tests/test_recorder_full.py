"""D5 mutation triage: CaptchaRecorder lifecycle + helpers, branch-complete.

Targets finish_updates (43), _outcome_payload (33), _checkpoint (33),
note_outcome (32), _drain_mutations (20), start (16), finish (13),
_event (13), __init__ (11), _milestone_event (6).
"""

import json
from types import SimpleNamespace

import pytest

from app.browser.cdp_events import CDPEventRouter
from app.services.captcha.signals import SolveOutcome
from app.services.captcha_recording.models import RecordingLimits
from app.services.captcha_recording.recorder import (
    CaptchaRecorder,
    _milestone_phase_for,
    as_dict,
    finish_updates,
)
from app.services.captcha_recording.store import RecordingStore, read_manifest

LIMITS = dict(poll_interval_sec=0.01, checkpoint_interval_sec=0,
              max_events=50, max_snapshots=5)


class FakeCDP:
    def __init__(self, router=True, snapshot_ok=True, drains=None):
        self.router = CDPEventRouter() if router else None
        self.snapshot_ok = snapshot_ok
        self.drains = list(drains or [])
        self.evaluated = []
        self.html_counter = 0

    @property
    def events(self):
        # recorder discovers the listener router via cdp.events
        return self.router

    async def evaluate(self, script):
        self.evaluated.append(script)
        if "queue.splice" in script:
            return {"ok": True, "changes": self.drains.pop(0) if self.drains else [],
                    "dropped": 0}
        if "cloneNode" in script:
            self.html_counter += 1
            if not self.snapshot_ok:
                return {"ok": False, "error": "boom"}
            return {"ok": True, "url": "https://arena.ai/c/1", "title": "Arena",
                    "viewport": {"w": 100, "h": 100},
                    "html": f"<html>state-{self.html_counter}</html>"}
        return {"ok": True}


def make_recorder(tmp_path, name="r", router=True, cdp_kwargs=None, **limits):
    cdp = FakeCDP(router=router, **(cdp_kwargs or {}))
    ctrl = SimpleNamespace(cdp=cdp)
    rec = CaptchaRecorder(RecordingStore(tmp_path / name), ctrl,
                          {"eid": "e1", "url": "https://arena.ai/c/1?k=v"},
                          RecordingLimits(**{**LIMITS, **limits}))
    return rec, cdp


def outcome(**over):
    base = dict(status="solved", method="auto", reason="accepted", task_id="t-1",
                polls=3, attempts=2, token_sec=1.5, dialog_at_token="div.d",
                inject="clicked", elapsed_sec=2.0)
    base.update(over)
    return SimpleNamespace(**base)


def read_events(rec):
    folder = rec.store.session_folder(rec.session_id)
    return [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]


class TestHelpers:
    def test_as_dict_variants(self):
        assert as_dict({"a": 1}) == {"a": 1}
        assert as_dict('{"a": 1}') == {"a": 1}
        assert as_dict("[1,2]") == {}
        assert as_dict("{broken") == {}
        assert as_dict(None) == {}
        assert as_dict(42) == {}

    def test_milestone_phase_for(self):
        assert _milestone_phase_for("final") == "final"
        assert _milestone_phase_for("auto_attempt_finished") == "auto_finished"
        assert _milestone_phase_for("weird") is None

    def test_outcome_payload_full(self):
        p = CaptchaRecorder._outcome_payload(outcome())
        assert p == {"state": "recording_finished", "outcome": "solved",
                     "method": "auto", "reason": "accepted"}

    def test_outcome_payload_missing_attrs(self):
        p = CaptchaRecorder._outcome_payload(SimpleNamespace())
        assert p["outcome"] == "interrupted"
        assert p["method"] == ""
        assert p["reason"] == ""

    def test_outcome_payload_redacts_reason(self):
        token = "T" * 90
        p = CaptchaRecorder._outcome_payload(outcome(reason=f"fail {token}"))
        assert token not in p["reason"]
        assert "[REDACTED_TOKEN]" in p["reason"]

    def test_finish_updates_full(self, tmp_path):
        rec, _ = make_recorder(tmp_path)
        rec._counts.update({"event": 5, "mutation": 2, "network": 3, "snapshot": 4})
        rec._truncated = {"events", "snapshots"}
        up = finish_updates(rec, outcome())
        assert up["status"] == "solved"
        assert up["outcome"] == "solved"
        assert up["reason"] == "accepted"
        assert up["method"] == "auto"
        assert up["task_id"] == "t-1"
        assert up["polls"] == 3
        assert up["attempts"] == 2
        assert up["event_count"] == 5
        assert up["mutation_count"] == 2
        assert up["network_count"] == 3
        assert up["snapshot_count"] == 4
        assert up["dropped_events"] == rec.network.dropped_events
        assert up["truncated"] == ["events", "snapshots"]
        assert up["elapsed_ms"] >= 0

    def test_finish_updates_defaults(self, tmp_path):
        rec, _ = make_recorder(tmp_path)
        up = finish_updates(rec, SimpleNamespace())
        assert up["status"] == "interrupted"
        assert up["polls"] == 0
        assert up["attempts"] == 1
        assert up["task_id"] == ""
        assert up["truncated"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_without_router(tmp_path):
    rec, cdp = make_recorder(tmp_path, name="a", router=False)
    await rec.start()
    assert rec.active is True
    assert rec.network in [getattr(cdp, "events", None)] or cdp.router is None
    await rec.finish(SolveOutcome(status="solved", method="auto", reason="ok"))
    assert rec.active is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_registers_listener(tmp_path):
    import asyncio
    rec, cdp = make_recorder(tmp_path, name="b")
    await rec.start()
    assert cdp.router is not None
    cdp.router.dispatch({"method": "Network.requestWillBeSent", "params": {
        "requestId": "1", "type": "Fetch",
        "request": {"url": "https://x.test/a", "method": "POST"}}})
    cdp.router.dispatch({"method": "Network.responseReceived", "params": {
        "requestId": "1", "type": "Fetch",
        "response": {"url": "https://x.test/a", "status": 200,
                     "mimeType": "application/json"}}})
    cdp.router.dispatch({"method": "Network.loadingFinished", "params": {"requestId": "1"}})
    await asyncio.sleep(0.02)
    await rec.finish(outcome())
    before = rec._counts["network"]
    assert before >= 1
    # listener removed — dispatching after finish adds nothing
    cdp.router.dispatch({"method": "Network.requestWillBeSent",
                         "params": {"requestId": "z", "type": "Fetch",
                                    "request": {"url": "https://x.test", "method": "GET"}}})
    cdp.router.dispatch({"method": "Network.responseReceived", "params": {
        "requestId": "z", "type": "Fetch",
        "response": {"url": "https://x.test", "status": 200,
                     "mimeType": "application/json"}}})
    cdp.router.dispatch({"method": "Network.loadingFinished", "params": {"requestId": "z"}})
    await rec.network.drain()
    assert rec._counts["network"] == before


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drain_mutations_counts_and_dropped(tmp_path):
    rec, cdp = make_recorder(tmp_path, name="c",
                             cdp_kwargs={"drains": [[{"op": "attr", "path": "div", "name": "data-x",
                                                      "old": "1", "new": "2"}]]})
    await rec._drain_mutations()
    assert rec._counts["mutation"] == 1
    kinds = [e["kind"] for e in read_events(rec)]
    assert "mutation" in kinds

    # dropped > 0 marks truncation
    cdp.drains.append([])
    # simulate dropped via direct evaluate result patch
    orig = cdp.evaluate

    async def eval2(script):
        r = await orig(script)
        if "queue.splice" in script:
            r["dropped"] = 4
        return r
    cdp.evaluate = eval2
    await rec._drain_mutations()
    assert "mutations" in rec._truncated

    # ok: False -> no changes
    async def eval3(script):
        if "queue.splice" in script:
            return {"ok": False}
        return {"ok": True}
    cdp.evaluate = eval3
    before = rec._counts["mutation"]
    await rec._drain_mutations()
    assert rec._counts["mutation"] == before


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkpoint_interval_and_hash(tmp_path):
    rec, cdp = make_recorder(tmp_path, name="d", checkpoint_interval_sec=999)
    await rec._checkpoint("first", force=True)
    assert rec._counts["snapshot"] == 1
    # within interval -> skipped
    await rec._checkpoint("second")
    assert rec._counts["snapshot"] == 1
    # forced same-html still writes
    await rec._checkpoint("forced", force=True)
    assert rec._counts["snapshot"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkpoint_max_snapshots(tmp_path):
    rec, cdp = make_recorder(tmp_path, name="e", max_snapshots=1)
    await rec._checkpoint("one", force=True)
    await rec._checkpoint("two", force=True)
    assert rec._counts["snapshot"] == 1
    assert "snapshots" in rec._truncated


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkpoint_probe_error(tmp_path):
    rec, cdp = make_recorder(tmp_path, name="f", cdp_kwargs={"snapshot_ok": False})
    await rec._checkpoint("x", force=True)
    assert rec._counts["snapshot"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_max_events(tmp_path):
    rec, _ = make_recorder(tmp_path, name="g", max_events=2)
    await rec._event("state", {"a": 1})
    await rec._event("state", {"b": 2})
    await rec._event("state", {"c": 3})
    assert rec._counts["event"] == 2
    assert "events" in rec._truncated
    assert len(read_events(rec)) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_network_flag(tmp_path):
    rec, _ = make_recorder(tmp_path, name="h")
    await rec._event("request", {"r": 1}, network=True)
    await rec._event("state", {"s": 1})
    assert rec._counts["network"] == 1
    assert rec._counts["event"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_note_outcome_payload(tmp_path):
    rec, _ = make_recorder(tmp_path, name="i")
    await rec.note_outcome("token_ready", outcome(token_sec=1.25, dialog_at_token="dlg"))
    states = [e for e in read_events(rec) if e["kind"] == "state"]
    payload = states[-1]
    assert payload["state"] == "token_ready"
    assert payload["token_at_ms"] == 1250
    assert payload["dialog_at_token"] == "dlg"
    assert payload["inject"] == "clicked"
    assert payload["outcome"] == "solved"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_note_outcome_unknown_phase_no_milestone(tmp_path):
    rec, _ = make_recorder(tmp_path, name="j")
    await rec.note_outcome("totally_unknown", outcome())
    kinds = [e["kind"] for e in read_events(rec)]
    assert "milestone" not in kinds
    assert "state" in kinds


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milestone_event_skipped_on_token(tmp_path):
    rec, _ = make_recorder(tmp_path, name="k")
    token = "Q" * 90
    await rec._milestone_event("final", outcome(reason=f"raw {token}"))
    events = read_events(rec)
    skipped = [e for e in events if e["kind"] == "milestone_skipped"]
    assert skipped and skipped[0]["why"] == "token-free check failed"
    assert not [e for e in events if e["kind"] == "milestone"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milestone_event_written(tmp_path):
    rec, _ = make_recorder(tmp_path, name="l")
    await rec._milestone_event("final", outcome())
    milestones = [e for e in read_events(rec) if e["kind"] == "milestone"]
    assert milestones
    assert milestones[0]["phase"] == "final"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_abort(tmp_path):
    rec, _ = make_recorder(tmp_path, name="m")
    await rec.start()
    await rec.abort("user_closed")  # -> None by design; inspect the manifest
    manifest = read_manifest(rec.store.session_folder(rec.session_id))
    assert manifest["status"] == "interrupted"
    assert manifest["outcome"] == "interrupted"
    assert manifest["reason"] == "user_closed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finish_full_lifecycle(tmp_path):
    rec, cdp = make_recorder(tmp_path, name="n")
    await rec.start()
    cdp.router.dispatch({"method": "Network.requestWillBeSent", "params": {
        "requestId": "1", "type": "Fetch",
        "request": {"url": "https://x.test/a?q=s", "method": "POST"}}})
    cdp.router.dispatch({"method": "Network.responseReceived", "params": {
        "requestId": "1", "type": "Fetch",
        "response": {"url": "https://x.test/a?q=s", "status": 200,
                     "mimeType": "application/json"}}})
    cdp.router.dispatch({"method": "Network.loadingFinished", "params": {"requestId": "1"}})
    manifest = await rec.finish(SolveOutcome(status="solved", method="auto", reason="ok"))
    assert manifest["status"] == "solved"
    assert manifest["event_count"] >= 1
    assert manifest["snapshot_count"] >= 1
    assert manifest["ended_at"]
