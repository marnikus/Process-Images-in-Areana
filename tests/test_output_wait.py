"""Tests for output_wait pure helpers and loop branches."""
import asyncio
import pytest
from app.browser.output_wait import (
    should_continue_after_spinner, is_ready_result, is_cancelled,
    handle_spinner_visible, handle_spinner_gone, handle_ready_result,
    handle_no_exact_below, handle_mismatch, _process_spinner, _check_cancelled,
    LoopState, WaitSpec, _check_timeout
)

def test_should_continue():
    assert should_continue_after_spinner("generating_spinner_visible")
    assert not should_continue_after_spinner("other")

def test_is_ready():
    assert is_ready_result({"ready": True})
    assert not is_ready_result({"ready": False})

def test_is_cancelled_none():
    assert not is_cancelled(None)

def test_is_cancelled_true():
    assert is_cancelled(lambda: True)
    assert not is_cancelled(lambda: False)

def test_is_cancelled_exception():
    def bad(): raise RuntimeError("boom")
    assert not is_cancelled(bad)

@pytest.mark.asyncio
async def test_handle_spinner_visible():
    logs=[]
    await handle_spinner_visible({"spinDetails": [{"label": "img"}]}, logs.append)
    assert any("Generating" in str(l) or "spinner" in str(l).lower() for l in logs)

@pytest.mark.asyncio
async def test_handle_spinner_gone():
    logs=[]
    await handle_spinner_gone(logs.append)
    assert len(logs)==1

@pytest.mark.asyncio
async def test_handle_ready_result_match():
    logs=[]
    diag={"associatedJobId": "A", "expectedJobId": "A", "top": 100}
    await handle_ready_result(diag, logs.append)
    assert any("verified" in str(l).lower() or "ready" in str(l).lower() for l in logs)

@pytest.mark.asyncio
async def test_handle_ready_result_mismatch():
    logs=[]
    diag={"associatedJobId": "A", "expectedJobId": "B"}
    await handle_ready_result(diag, logs.append)
    assert any("mismatch" in str(l).lower() for l in logs)

@pytest.mark.asyncio
async def test_handle_no_exact_below_mismatch():
    logs=[]
    diag={"reason": "job_id_mismatch", "expectedJobId": "X", "mismatchDetails": [{"associated": "Y"}]}
    await handle_no_exact_below(diag, logs.append)
    assert any("mismatch" in str(l).lower() for l in logs)

@pytest.mark.asyncio
async def test_handle_no_exact_below_normal():
    logs=[]
    diag={"reason": "no_exact_below_found_wait_next", "jobTop": 10, "prevJobTop": 5, "allNew": 1, "validBelow": 0, "validAbove": 0, "expectedJobId": "Z"}
    await handle_no_exact_below(diag, logs.append)
    assert len(logs)>=1

@pytest.mark.asyncio
async def test_handle_mismatch():
    logs=[]
    diag={"expectedJobId": "X", "mismatchDetails": [{"a": 1}], "poolDetails": []}
    await handle_mismatch(diag, logs.append)
    assert any("verification failed" in str(l).lower() or "mismatch" in str(l).lower() for l in logs)

@pytest.mark.asyncio
async def test_process_spinner_visible():
    logs=[]
    diag={"reason": "generating_spinner_visible", "spinning": True}
    res = await _process_spinner(diag, logs.append, False)
    assert res is True

@pytest.mark.asyncio
async def test_process_spinner_gone():
    logs=[]
    diag={"reason": "done", "spinning": False}
    res = await _process_spinner(diag, logs.append, True)
    assert res is False

@pytest.mark.asyncio
async def test_check_cancelled():
    state = LoopState(last={}, start=0)
    res = await _check_cancelled(lambda: True, state)
    assert res is not None
    assert res["reason"] == "cancelled"
    res2 = await _check_cancelled(lambda: False, state)
    assert res2 is None

@pytest.mark.asyncio
async def test_check_timeout_not_yet(monkeypatch):
    import time
    state = LoopState(last={"ready": False}, start=time.monotonic())
    spec = WaitSpec(timeout=100, poll_interval=0.1)
    res = await _check_timeout(state, spec, lambda m: None)
    assert res is None

@pytest.mark.asyncio
async def test_check_timeout_expired(monkeypatch):
    import time
    state = LoopState(last={"ready": False, "reason": "other"}, start=time.monotonic() - 200)
    spec = WaitSpec(timeout=1, poll_interval=0.1)
    async def fake_sleep(_): return None
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    # mock _handle_timeout_fallback to return None
    import app.browser.output_wait as mod
    async def fake_fb(last, timeout, log_cb): return None
    monkeypatch.setattr(mod, "_handle_timeout_fallback", fake_fb)
    res = await _check_timeout(state, spec, lambda m: None)
    assert res is not None
    assert res["reason"] == "timeout"
