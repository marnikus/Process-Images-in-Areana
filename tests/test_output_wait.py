"""Characterization + contract tests for output_wait (roadmap W0.2).

RULE 8: these lock the observable loop contract BEFORE and AFTER the
WaitSpec/_poll_once refactor — same inputs, same results.
"""

from __future__ import annotations



import pytest

from app.browser.output_wait import (
    WaitSpec,
    _handle_timeout_fallback,
    _process_fallback,
    _process_ready,
    should_fallback,
    wait_for_new_output_loop,
)


def _diag(**kw):
    base = {"ready": False, "reason": "generating_no_new_yet", "spinning": True,
            "allNew": 0, "validBelow": 0, "validAbove": 0, "mismatchDetails": []}
    base.update(kw)
    return base


class Log:
    """Callable log collector (stands in for the bridge logger)."""

    def __init__(self):
        self.lines = []

    def __call__(self, msg):
        self.lines.append(msg)


@pytest.mark.asyncio
async def test_loop_returns_ready_result_with_matching_job():
    ready = _diag(ready=True, src="https://r2/a.png", associatedJobId="J1", expectedJobId="J1")
    rechecks = [ready]  # stabilization re-check confirms

    async def check_fn():
        return dict(rechecks[0])

    res = await wait_for_new_output_loop(WaitSpec(check_fn=check_fn, log_cb=Log(), timeout=5, poll_interval=0.01))
    assert res["ready"] is True
    assert res["src"] == "https://r2/a.png"


@pytest.mark.asyncio
async def test_loop_cancel_returns_cancelled_with_last_diag():
    calls = {"n": 0}

    async def check_fn():
        calls["n"] += 1
        return _diag(spinning=True)

    res = await wait_for_new_output_loop(WaitSpec(check_fn=check_fn, log_cb=Log(),
                                         cancel_check=lambda: calls["n"] > 1,
                                         timeout=5, poll_interval=0.01))
    assert res["ready"] is False
    assert res["reason"] == "cancelled"
    assert res["last"]["reason"] == "generating_no_new_yet"


@pytest.mark.asyncio
async def test_loop_timeout_without_candidates_returns_timeout():
    async def check_fn():
        return _diag(spinning=False)

    res = await wait_for_new_output_loop(WaitSpec(check_fn=check_fn, log_cb=Log(),
                                         timeout=0.05, poll_interval=0.01))
    assert res["ready"] is False
    assert res["reason"] == "timeout"
    assert "elapsed" in res


@pytest.mark.asyncio
async def test_loop_timeout_fallback_stable_image():
    stable = _diag(reason="no_exact_below_found_wait_next", spinning=False,
                   allNew=1, src="https://r2/b.png",
                   associatedJobId="J2", expectedJobId="J2")

    async def check_fn():
        return dict(stable)

    res = await wait_for_new_output_loop(WaitSpec(check_fn=check_fn, log_cb=Log(),
                                         timeout=0.05, poll_interval=0.01))
    assert res["ready"] is True and res["fallback"] is True
    assert res["src"] == "https://r2/b.png"


@pytest.mark.asyncio
async def test_loop_timeout_mismatch_never_falls_back():
    mismatch = _diag(reason="job_id_mismatch_no_matching_image", spinning=False,
                     allNew=1, mismatchDetails=[{"associated": "OTHER"}],
                     associatedJobId="OTHER", expectedJobId="J3")

    async def check_fn():
        return dict(mismatch)

    res = await wait_for_new_output_loop(WaitSpec(check_fn=check_fn, log_cb=Log(),
                                         timeout=0.05, poll_interval=0.01))
    assert res["ready"] is False
    assert res["reason"] == "job_id_mismatch_no_matching_image"


@pytest.mark.asyncio
async def test_loop_recheck_mismatch_rejects_ready():
    """Ready result whose 3s re-check flips to a mismatch is NOT returned."""
    first = _diag(ready=True, src="https://r2/c.png",
                  associatedJobId="J4", expectedJobId="J4")
    flipped = _diag(ready=True, src="https://r2/c.png",
                    associatedJobId="OTHER", expectedJobId="J4")
    seq = [first, flipped, flipped]

    async def check_fn():
        return dict(seq.pop(0))

    res = await wait_for_new_output_loop(WaitSpec(check_fn=check_fn, log_cb=Log(),
                                         timeout=5, poll_interval=0.01))
    # CHARACTERIZED ANOMALY (locked, flagged): when the 3s re-check flips
    # to a mismatch but the ORIGINAL diag shows assoc==expected and a
    # non-mismatch reason, the loop still returns the original ready diag
    # (the recheck rejection only blocks when the original diag itself
    # signals mismatch). Behaviour change needs an owner decision.
    assert res["ready"] is True
    assert res["src"] == "https://r2/c.png"


@pytest.mark.unit
def test_should_fallback_truth_table():
    t = _diag(allNew=1, validBelow=0, validAbove=0, spinning=False, elapsed_diag=None)
    assert should_fallback(15, _diag(allNew=1, validBelow=0, validAbove=0, spinning=False)) is True
    # never under 10s
    assert should_fallback(5, _diag(allNew=1, validBelow=0, validAbove=0)) is False
    # never on strict mismatch
    assert should_fallback(15, _diag(reason="job_id_mismatch_no_matching_image")) is False
    # mismatched-only images: do not fallback
    assert should_fallback(15, _diag(allNew=2, mismatchDetails=[{"a": 1}],
                                     validBelow=0, validAbove=0)) is False
    # CHARACTERIZED: allNew>0 with no valid pools falls back EVEN while
    # spinning (the spinning check only guards the later branch) — locked
    # as-is; changing it is a deliberate behaviour decision.
    assert should_fallback(15, _diag(allNew=1, spinning=True)) is True
    # nothing new: no fallback
    assert should_fallback(15, _diag(allNew=0)) is False


@pytest.mark.asyncio
async def test_timeout_fallback_rejects_association_mismatch():
    last = _diag(reason="no_exact_below_found_wait_next", allNew=1, src="x",
                 associatedJobId="OTHER", expectedJobId="J9")
    res = await _handle_timeout_fallback(last, 30, Log())
    assert res is None  # mismatched image must not be used


@pytest.mark.asyncio
async def test_process_fallback_marks_ready_and_flag():
    diag = _diag(allNew=1, validBelow=0, validAbove=0, spinning=False,
                 src="https://r2/d.png", associatedJobId="J5", expectedJobId="J5")
    res = await _process_fallback(diag, 12.0, Log())
    assert res is diag and diag["ready"] is True and diag["fallback"] is True


@pytest.mark.asyncio
async def test_process_ready_returns_diag_when_recheck_confirms():
    diag = _diag(ready=True, src="s", associatedJobId="J6", expectedJobId="J6")

    async def check_fn():
        return dict(diag)

    res = await _process_ready(diag, check_fn, Log())
    # the re-check's FLATTENED dict is returned (not the original object)
    assert res is not diag
    assert res["ready"] is True and res["src"] == "s"


@pytest.mark.asyncio
async def test_process_ready_rejects_association_mismatch():
    diag = _diag(ready=True, src="s", associatedJobId="OTHER", expectedJobId="J7")

    async def check_fn():
        return {}

    res = await _process_ready(diag, check_fn, Log())
    assert res is None
