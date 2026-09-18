"""Recorder executes real lifecycle against a fake CDP transport."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.browser.cdp_events import CDPEventRouter
from app.services.captcha.signals import SolveOutcome
from app.services.captcha_recording.models import RecordingLimits
from app.services.captcha_recording.recorder import CaptchaRecorder
from app.services.captcha_recording.store import RecordingStore


class FakeRecordingCDP:
    def __init__(self):
        self.events = CDPEventRouter()
        self.drains = [[{"op": "attr", "path": "div[role=dialog]", "name": "data-state",
                         "old": "open", "new": "closed"}], []]
        self.sent = []

    async def evaluate(self, script):
        if "queue.splice" in script:
            changes = self.drains.pop(0) if self.drains else []
            return {"ok": True, "changes": changes, "dropped": 0}
        if "cloneNode" in script:
            return {"ok": True, "url": "https://arena.ai/c/1", "title": "Arena",
                    "viewport": {"w": 100, "h": 100}, "html": "<html><main>state</main></html>"}
        return {"ok": True}

    async def send(self, method, params, timeout=5):
        self.sent.append((method, params, timeout))
        return {"result": {"body": '{"token":"' + "A" * 100 + '"}', "base64Encoded": False}}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recorder_captures_diff_network_body_and_finish(tmp_path):
    cdp = FakeRecordingCDP()
    ctrl = SimpleNamespace(cdp=cdp)
    limits = RecordingLimits(poll_interval_sec=0.01, checkpoint_interval_sec=0,
                             max_events=100, max_snapshots=5)
    encounter = {"eid": "e1", "tab": "t1", "url": "https://arena.ai/c/1?secret=x",
                 "source": "test", "kind": "recaptcha_enterprise"}
    recorder = CaptchaRecorder(RecordingStore(tmp_path), ctrl, encounter, limits)
    await recorder.start()

    cdp.events.dispatch({"method": "Network.requestWillBeSent", "params": {
        "requestId": "1", "type": "Fetch", "request": {"url": "https://arena.ai/api/x?q=secret", "method": "POST"}}})
    cdp.events.dispatch({"method": "Network.responseReceived", "params": {
        "requestId": "1", "type": "Fetch", "response": {"url": "https://arena.ai/api/x?q=secret",
        "status": 200, "mimeType": "application/json"}}})
    cdp.events.dispatch({"method": "Network.loadingFinished", "params": {"requestId": "1"}})
    await asyncio.sleep(0.03)
    result = await recorder.finish(SolveOutcome(status="solved", method="auto", reason="accepted"))

    folder = recorder.store.session_folder(recorder.session_id)
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
    assert result["outcome"] == "solved" and result["method"] == "auto"
    assert any(event["kind"] == "mutation" for event in events)
    assert any(event["kind"] == "response_body" for event in events)
    assert "?q=" not in json.dumps(events)
    assert "A" * 100 not in json.dumps(events)
    assert cdp.sent[0][0] == "Network.getResponseBody"
    assert result["snapshot_count"] >= 1 and result["network_count"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_network_collector_no_loss_across_threads():
    """P9/H5: events are appended from a worker thread while the loop drains."""
    import threading
    import time

    from app.services.captcha_recording.network import NetworkCollector

    recorded = []

    async def sink(kind, payload, network):
        recorded.append((kind, payload))

    async def send(method, params, timeout=5):
        return {"result": {}}

    collector = NetworkCollector(SimpleNamespace(send=send), sink, 1000, set().add)

    def feeder():
        for i in range(500):
            collector.on_event({"method": "Network.requestWillBeSent",
                                "params": {"requestId": str(i), "type": "Fetch",
                                           "request": {"url": f"https://x.test/{i}",
                                                       "method": "GET"}}})
            if i % 50 == 0:
                time.sleep(0.002)

    thread = threading.Thread(target=feeder)
    thread.start()
    while thread.is_alive():
        await collector.drain()
        await asyncio.sleep(0.001)
    await collector.drain()
    thread.join()
    assert len(recorded) == 500  # zero loss
    assert recorded[0][0] == "network_request"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finish_manifest_carries_attempt_evidence(tmp_path):
    """H5: manifest persists task_id/polls/attempts (bounded, token-free)."""
    cdp = FakeRecordingCDP()
    ctrl = SimpleNamespace(cdp=cdp)
    limits = RecordingLimits(poll_interval_sec=0.01, checkpoint_interval_sec=0,
                             max_events=100, max_snapshots=5)
    encounter = {"eid": "e2", "tab": "t2", "url": "https://arena.ai/c/2",
                 "source": "test", "kind": "recaptcha_enterprise"}
    recorder = CaptchaRecorder(RecordingStore(tmp_path), ctrl, encounter, limits)
    await recorder.start()
    outcome = SolveOutcome(status="solved", method="auto", task_id="42", polls=3,
                           attempts=2, reason="accepted")
    result = await recorder.finish(outcome)
    assert result["task_id"] == "42" and result["polls"] == 3 and result["attempts"] == 2
