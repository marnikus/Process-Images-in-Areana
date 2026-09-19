"""Async tests for fallback handlers."""
import asyncio
import pytest
from app.browser.output_wait_fallback import _handle_timeout_fallback, _recheck_after_delay, _process_fallback

@pytest.mark.asyncio
async def test_handle_timeout_fallback_mismatch():
    logs = []
    res = await _handle_timeout_fallback({"reason": "job_id_mismatch_no_matching_image"}, 180, logs.append)
    assert res is None

@pytest.mark.asyncio
async def test_handle_timeout_fallback_assoc_mismatch():
    logs = []
    diag = {"allNew": 1, "src": "http://x", "associatedJobId": "A", "expectedJobId": "B"}
    res = await _handle_timeout_fallback(diag, 180, logs.append)
    assert res is None
    assert any("mismatched" in str(l).lower() or "NOT using" in str(l) for l in logs)

@pytest.mark.asyncio
async def test_handle_timeout_fallback_success(monkeypatch):
    logs = []
    diag = {"allNew": 1, "src": "http://x", "associatedJobId": "A", "expectedJobId": "A"}
    async def fake_sleep(_): return None
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    res = await _handle_timeout_fallback(diag, 180, logs.append)
    assert res is not None
    assert res.get("fallback") is True

@pytest.mark.asyncio
async def test_recheck_mismatch(monkeypatch):
    logs = []
    async def check_fn():
        return {"associatedJobId": "A", "expectedJobId": "B", "ready": True}
    async def fake_sleep(_): return None
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    # need to mock flatten_diagnostics
    import app.browser.output_wait_fallback as mod
    monkeypatch.setattr(mod, "flatten_diagnostics", lambda x: x, raising=False)
    # Actually flatten is imported inside function from .output_state, we need to patch that module
    import sys
    import types
    # create dummy output_state module if not present
    # We'll monkeypatch the function to avoid import error by making check_fn return already flattened
    # Instead patch inside _recheck_after_delay to bypass import: we will directly test _has_assoc_mismatch path
    # Simpler: mock the import via sys.modules
    dummy = types.ModuleType("app.browser.output_state")
    dummy.flatten_diagnostics = lambda x: x
    sys.modules["app.browser.output_state"] = dummy
    res = await _recheck_after_delay(check_fn, logs.append)
    assert res is None

@pytest.mark.asyncio
async def test_process_fallback(monkeypatch):
    logs = []
    async def fake_sleep(_): return None
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    diag = {"allNew": 1, "validBelow": 0, "validAbove": 0, "src": "http://x"}
    res = await _process_fallback(diag, 20, logs.append)
    assert res is not None
    assert res.get("fallback") is True
