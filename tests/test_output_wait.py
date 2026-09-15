"""Tests for output_wait polling — fake CDP, real loop logic."""

import pytest

from app.browser.output_wait import WaitRequest, wait_for_new


class FakeCdp:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def evaluate(self, js):
        self.calls += 1
        assert "JOB" in js or "oldKeys" in js or "scroll" in js.lower() or "no-scrollbar" in js
        if not self.results:
            return None
        item = self.results[0]
        if isinstance(item, list):
            # pop one per call for sequences
            return item.pop(0) if item else None
        return self.results.pop(0)


def _logs():
    out = []
    def log_fn(msg, level="info"):
        out.append((msg, level))
    return log_fn, out


@pytest.mark.asyncio
async def test_ready_immediately():
    cdp = FakeCdp([{"ready": True, "src": "https://x/gen.png", "spinning": False}])
    log_fn, logs = _logs()
    req = WaitRequest(baseline={"output_srcs": []}, timeout_ms=5000)
    status, data = await wait_for_new(cdp, log_fn, req)
    assert status == "completed"
    assert data["new_src"].endswith("gen.png")
    assert any("ready" in m.lower() for m, _ in logs)


@pytest.mark.asyncio
async def test_spinning_then_ready():
    cdp = FakeCdp([
        {"ready": False, "spinning": True, "spinCount": 1, "reason": "generating_no_new_yet"},
        {"ready": True, "src": "https://x/done.png", "spinning": False},
    ])
    log_fn, logs = _logs()
    req = WaitRequest(baseline={"output_srcs": []}, timeout_ms=8000, poll_sec=1)
    status, data = await wait_for_new(cdp, log_fn, req)
    assert status == "completed"
    assert "done.png" in data["new_src"]
    assert any("spinner" in m.lower() or "generation" in m.lower() for m, _ in logs)


@pytest.mark.asyncio
async def test_cancel_honoured_promptly():
    cdp = FakeCdp([{"ready": False, "spinning": True}])
    log_fn, _ = _logs()
    req = WaitRequest(baseline={}, timeout_ms=8000, cancel_check=lambda: True)
    status, data = await wait_for_new(cdp, log_fn, req)
    assert status == "failed"
    assert data.get("cancelled") is True


@pytest.mark.asyncio
async def test_timeout_when_no_result():
    cdp = FakeCdp([None, None, None])
    log_fn, _ = _logs()
    req = WaitRequest(baseline={}, timeout_ms=2500, poll_sec=1)
    status, data = await wait_for_new(cdp, log_fn, req)
    assert status == "failed"
    assert "Timeout" in data["error"]


@pytest.mark.asyncio
async def test_fallback_after_stable_large():
    details = [{"src": "https://x/stable.png", "width": 800, "top": 900, "isLarge": True}]
    waiting = {
        "ready": False, "spinning": False, "reason": "no_exact_above_found_wait_next",
        "allNewDetails": details, "allNew": 1, "jobFound": True,
    }
    # Need stable 3x plus elapsed 10s: use short timeout but monkeypatch time?
    # Instead, verify no fallback before stability (2 polls, short timeout).
    cdp = FakeCdp([dict(waiting), dict(waiting)])
    log_fn, _ = _logs()
    req = WaitRequest(baseline={}, timeout_ms=2500, poll_sec=1)
    status, _ = await wait_for_new(cdp, log_fn, req)
    assert status == "failed"


@pytest.mark.asyncio
async def test_decide_done_accepts_stable_fallback():
    import time as time_mod
    from app.browser.output_wait import _WaitState, _decide_done
    log_fn, logs = _logs()
    # Simulate 11s elapsed, already stable 2x, third same src makes 3x
    state = _WaitState(start=time_mod.time() - 11, keys=frozenset())
    state.stable_src = "https://x/stable.png"
    state.stable_count = 2
    result = {
        "ready": False, "spinning": False, "reason": "no_exact_above_found_wait_next",
        "allNewDetails": [{"src": "https://x/stable.png", "width": 800, "top": 900, "isLarge": True}],
    }
    done, payload = _decide_done(log_fn, result, state)
    assert done is True
    assert payload[0] == "completed"
    assert payload[1]["new_src"].endswith("stable.png")
    assert payload[1].get("fallback") is True
    assert state.stable_count == 3


def test_decide_done_rejects_unstable():
    import time as time_mod
    from app.browser.output_wait import _WaitState, _decide_done
    log_fn, _ = _logs()
    state = _WaitState(start=time_mod.time(), keys=frozenset())
    result = {
        "ready": False, "spinning": False, "reason": "no_new",
        "allNewDetails": [{"src": "https://x/a.png", "width": 800, "top": 900, "isLarge": True}],
    }
    done, _ = _decide_done(log_fn, result, state)
    assert done is False
    assert state.stable_count == 1
