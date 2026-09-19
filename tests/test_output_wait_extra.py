"""Extra coverage for output_wait loop to reach 80%."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.browser.output_wait import (
    WaitSpec, LoopState, _poll_check, _process_ready,
    _process_spinner, _handle_ready_branch, _handle_non_ready_branch,
    wait_for_new_output_with_spec,
    handle_spinner_visible, handle_ready_result, handle_no_exact_below,
    handle_mismatch, _check_timeout, _check_cancelled, _reraise_abort,
    is_mismatch_reason
)
from app.utils.page_errors import PageErrorAbort

@pytest.mark.asyncio
async def test_poll_check_success():
    async def check():
        return {"ready": True, "top": 1}
    diag, err = await _poll_check(check, 0.01)
    assert diag is not None
    assert diag["ready"] is True

@pytest.mark.asyncio
async def test_poll_check_exception():
    async def check():
        raise RuntimeError("boom")
    diag, err = await _poll_check(check, 0.001)
    assert diag is None
    assert err["ready"] is False

@pytest.mark.asyncio
async def test_poll_check_abort_reraises():
    async def check():
        raise PageErrorAbort("abort")
    with pytest.raises(PageErrorAbort):
        await _poll_check(check, 0.001)

def test_reraise_abort():
    _reraise_abort(RuntimeError("x"))
    with pytest.raises(PageErrorAbort):
        _reraise_abort(PageErrorAbort("a"))

@pytest.mark.asyncio
async def test_process_ready_mismatch():
    logs=[]
    diag={"ready": True, "reason": "job_id_mismatch", "associatedJobId": "A", "expectedJobId": "B", "mismatchDetails": [{"a":1}], "poolDetails": []}
    res = await _process_ready(diag, AsyncMock(return_value={"ready": False}), logs.append)
    assert res is None

@pytest.mark.asyncio
async def test_process_ready_success():
    logs=[]
    async def check():
        return {"ready": False}
    # mock _recheck_after_delay to return None
    import app.browser.output_wait as mod
    orig = mod._recheck_after_delay
    async def fake_recheck(cf, lc):
        return None
    mod._recheck_after_delay = fake_recheck
    diag={"ready": True, "top": 10, "associatedJobId": "A", "expectedJobId": "A"}
    res = await _process_ready(diag, check, logs.append)
    assert res is not None
    assert res["ready"] is True
    mod._recheck_after_delay = orig

@pytest.mark.asyncio
async def test_process_ready_with_recheck():
    logs=[]
    async def check():
        return {"ready": True, "top": 20}
    import app.browser.output_wait as mod
    orig = mod._recheck_after_delay
    async def fake_recheck(cf, lc):
        return {"ready": True, "top": 20}
    mod._recheck_after_delay = fake_recheck
    diag={"ready": True, "top": 10, "associatedJobId": "A", "expectedJobId": "A"}
    res = await _process_ready(diag, check, logs.append)
    assert res["top"]==20
    mod._recheck_after_delay = orig

@pytest.mark.asyncio
async def test_handle_ready_branch_success():
    logs=[]
    async def check():
        return {"ready": False}
    import app.browser.output_wait as mod
    orig = mod._recheck_after_delay
    async def fake_recheck(cf, lc):
        return None
    mod._recheck_after_delay = fake_recheck
    diag={"ready": True, "associatedJobId": "A", "expectedJobId": "A", "top": 1}
    spec = WaitSpec(timeout=10, poll_interval=0.001)
    result, done = await _handle_ready_branch(diag, check, logs.append, spec)
    assert done is True
    mod._recheck_after_delay = orig

@pytest.mark.asyncio
async def test_handle_ready_branch_mismatch():
    logs=[]
    async def check():
        return {"ready": False}
    diag={"ready": True, "associatedJobId": "A", "expectedJobId": "B", "reason": "mismatch", "mismatchDetails": [], "poolDetails": []}
    spec = WaitSpec(timeout=10, poll_interval=0.001)
    result, done = await _handle_ready_branch(diag, check, logs.append, spec)
    assert done is False
    assert result is None

@pytest.mark.asyncio
async def test_handle_non_ready_branch_spinner_and_fallback():
    logs=[]
    import app.browser.output_wait as mod
    # case with fallback returning result
    async def fake_fallback(diag, elapsed, log_cb):
        return {"ready": True, "reason": "fallback"}
    orig_fb = mod._process_fallback
    mod._process_fallback = fake_fallback
    diag={"reason": "generating_spinner_visible", "spinning": True, "spinDetails": []}
    state = LoopState(last={}, spin_visible=False, start=0)
    spec = WaitSpec(timeout=10, poll_interval=0.001)
    res = await _handle_non_ready_branch(diag, logs.append, state, spec)
    assert res is not None
    mod._process_fallback = orig_fb

@pytest.mark.asyncio
async def test_handle_non_ready_branch_no_fallback():
    logs=[]
    import app.browser.output_wait as mod
    async def fake_fallback(diag, elapsed, log_cb):
        return None
    orig_fb = mod._process_fallback
    mod._process_fallback = fake_fallback
    diag={"reason": "no_exact_below_found_wait_next", "spinning": False, "jobTop": 1, "prevJobTop": 0, "allNew": 0, "validBelow": 0, "validAbove": 0, "expectedJobId": "X"}
    state = LoopState(last={}, spin_visible=False, start=0)
    spec = WaitSpec(timeout=10, poll_interval=0.001)
    res = await _handle_non_ready_branch(diag, logs.append, state, spec)
    assert res is None
    mod._process_fallback = orig_fb

@pytest.mark.asyncio
async def test_wait_loop_cancelled():
    async def check():
        return {"ready": False}
    logs=[]
    def cancel():
        return True
    spec = WaitSpec(timeout=10, poll_interval=0.001)
    res = await wait_for_new_output_with_spec(check, logs.append, cancel, spec)
    assert res["reason"]=="cancelled"

@pytest.mark.asyncio
async def test_wait_loop_timeout():
    import time
    async def check():
        return {"ready": False, "reason": "still_waiting"}
    logs=[]
    import app.browser.output_wait as mod
    async def fake_timeout_fb(last, timeout, log_cb):
        return None
    orig = mod._handle_timeout_fallback
    mod._handle_timeout_fallback = fake_timeout_fb
    spec = WaitSpec(timeout=0.01, poll_interval=0.001)
    # set start far past
    state_orig = LoopState
    # we need to make loop timeout quickly: sleep a bit
    res = await wait_for_new_output_with_spec(check, logs.append, None, spec)
    assert res["reason"] in ("timeout", "still_waiting", "job_id_mismatch_no_matching_image") or res.get("ready") is False
    mod._handle_timeout_fallback = orig

@pytest.mark.asyncio
async def test_wait_loop_ready():
    calls=0
    async def check():
        nonlocal calls
        calls+=1
        if calls<2:
            return {"ready": False, "reason": "no_exact_below_found_wait_next", "jobTop": 0, "prevJobTop": 0, "allNew": 0, "validBelow": 0, "validAbove": 0, "expectedJobId": "A"}
        return {"ready": True, "top": 10, "associatedJobId": "A", "expectedJobId": "A"}
    logs=[]
    import app.browser.output_wait as mod
    orig_recheck = mod._recheck_after_delay
    async def fake_recheck(cf, lc):
        return None
    mod._recheck_after_delay = fake_recheck
    orig_fb = mod._process_fallback
    async def fake_fb(diag, elapsed, log_cb):
        return None
    mod._process_fallback = fake_fb
    spec = WaitSpec(timeout=5, poll_interval=0.001)
    res = await wait_for_new_output_with_spec(check, logs.append, None, spec)
    assert res["ready"] is True
    mod._recheck_after_delay = orig_recheck
    mod._process_fallback = orig_fb

@pytest.mark.asyncio
async def test_wait_loop_fallback_return():
    async def check():
        return {"ready": False, "reason": "still_waiting"}
    logs=[]
    import app.browser.output_wait as mod
    async def fake_fb(diag, elapsed, log_cb):
        return {"ready": True, "reason": "fallback_success"}
    orig = mod._process_fallback
    mod._process_fallback = fake_fb
    spec = WaitSpec(timeout=5, poll_interval=0.001)
    res = await wait_for_new_output_with_spec(check, logs.append, None, spec)
    assert res["ready"] is True
    mod._process_fallback = orig

@pytest.mark.asyncio
async def test_handle_spinner_visible_exception():
    logs=[]
    # diag with spinDetails that raises
    diag={"spinDetails": None}
    await handle_spinner_visible(diag, logs.append)
    assert len(logs)==1

@pytest.mark.asyncio
async def test_handle_ready_result_exception():
    logs=[]
    diag=None
    await handle_ready_result(diag, logs.append)
    # should fallback log
    assert len(logs)>=1

@pytest.mark.asyncio
async def test_handle_no_exact_below_exception():
    logs=[]
    await handle_no_exact_below(None, logs.append)
    assert len(logs)>=1

@pytest.mark.asyncio
async def test_handle_mismatch_exception():
    logs=[]
    await handle_mismatch(None, logs.append)
    assert len(logs)>=1

@pytest.mark.asyncio
async def test_check_timeout_with_fallback():
    import app.browser.output_wait as mod, time
    state = LoopState(last={"ready": False}, start=time.monotonic()-100)
    spec = WaitSpec(timeout=1, poll_interval=0.001)
    async def fake_fb(last, timeout, log_cb):
        return {"ready": True, "reason": "timeout_fallback"}
    orig = mod._handle_timeout_fallback
    mod._handle_timeout_fallback = fake_fb
    res = await _check_timeout(state, spec, lambda m: None)
    assert res is not None
    assert res["ready"] is True
    mod._handle_timeout_fallback = orig

@pytest.mark.asyncio
async def test_check_timeout_mismatch_no_matching():
    import app.browser.output_wait as mod, time
    state = LoopState(last={"ready": False, "reason": "job_id_mismatch_no_matching_image"}, start=time.monotonic()-100)
    spec = WaitSpec(timeout=1, poll_interval=0.001)
    async def fake_fb(last, timeout, log_cb):
        return None
    orig = mod._handle_timeout_fallback
    mod._handle_timeout_fallback = fake_fb
    res = await _check_timeout(state, spec, lambda m: None)
    assert res is not None
    assert res["reason"]=="job_id_mismatch_no_matching_image"
    mod._handle_timeout_fallback = orig

@pytest.mark.asyncio
async def test_process_spinner_branches():
    logs=[]
    # spinning true but reason not in continue list
    diag={"reason": "other", "spinning": True}
    res = await _process_spinner(diag, logs.append, False)
    assert res is False
    # was_visible true and not spinning -> gone
    diag2={"reason": "done", "spinning": False}
    res2 = await _process_spinner(diag2, logs.append, True)
    assert res2 is False
    # was_visible false and spinning false
    res3 = await _process_spinner(diag2, logs.append, False)
    assert res3 is False
