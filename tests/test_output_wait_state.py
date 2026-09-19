"""D4.4: output_wait + output_state branch coverage (wait-loop decision table).

The pure decision functions (should_fallback / mismatch routing / timeout
fallback) are the branch-dense core of the generation wait; every arm is
exercised with a crafted diagnostics dict. RULE 8: real modules, no fakes.
"""

import pytest

from app.browser import output_state as ost
from app.browser import output_wait as ow
from app.utils.page_errors import PageErrorAbort

pytestmark = pytest.mark.unit


def logs():
    return []


# ── output_state ──

def test_flatten_diagnostics_defaults_and_invalid():
    assert ost.flatten_diagnostics({"ready": True})["jobFound"] is False
    bad = ost.flatten_diagnostics(["not a dict"])
    assert bad == {"ready": False, "reason": "invalid_result"}


def test_build_order_check_text_layouts():
    text = ost.build_order_check_text({"jobTop": 1, "prevJobTop": 0, "nextJobTop": 2,
                                       "layoutReverse": True, "associatedJobId": "a",
                                       "orderCheck": "ok"})
    assert "layout reverse" in text and "associated a" in text
    fallback = ost.build_order_check_text({"expectedJobId": None, "jobId": "jb"})
    assert "expected jb" in fallback and "layout normal" in fallback


def test_output_state_small_helpers():
    assert ost.should_use_below_pool({"validBelow": 1}) is True
    assert ost.should_use_below_pool({"belowCount": 2}) is True
    assert ost.should_use_below_pool({}) is False
    assert ost.extract_rect({"rect": {"x": 1}}) == {"x": 1}
    assert ost.extract_rect({"rect": 5}) is None
    assert ost.extract_src({"src": "https://a/b.png"}) == "https://a/b.png"
    assert ost.extract_src({"src": "blob:x"}) is None
    assert ost.extract_src({}) is None
    assert ost.is_job_id_match({"expectedJobId": None}) is True
    assert ost.is_job_id_match({"expectedJobId": "e", "associatedJobId": None}) is True
    assert ost.is_job_id_match({"expectedJobId": "e", "associatedJobId": "e"}) is True
    assert ost.is_job_id_match({"expectedJobId": "e", "associatedJobId": "x"}) is False
    assert ost.is_mismatch_error({"reason": "job_id_mismatch"}) is True
    assert ost.is_mismatch_error({"reason": "job_id_mismatch_no_matching_image"}) is True
    assert ost.is_mismatch_error({"reason": "waiting"}) is False


# ── output_wait: cancellation + fallback decision table ──

def test_is_cancelled_arms():
    assert ow.is_cancelled(None) is False
    assert ow.is_cancelled(lambda: True) is True
    assert ow.is_cancelled(lambda: False) is False

    def boom():
        raise RuntimeError("cancel check down")
    assert ow.is_cancelled(boom) is False


def test_should_fallback_decision_table():
    d = {"allNew": 1, "validBelow": 0, "validAbove": 0, "spinning": False}
    assert ow.should_fallback(5.0, d) is False  # too early
    assert ow.should_fallback(11.0, {**d, "reason": "job_id_mismatch_no_matching_image"}) is False
    assert ow.should_fallback(11.0, {**d, "mismatchDetails": [{"a": 1}]}) is False  # only mismatched
    assert ow.should_fallback(11.0, d) is True  # all new, nothing valid below/above
    assert ow.should_fallback(11.0, {"allNew": 2, "spinning": False}) is True
    assert ow.should_fallback(11.0, {"allNew": 2, "spinning": False,
                                     "mismatchDetails": [{"a": 1}]}) is False
    assert ow.should_fallback(11.0, {"allNew": 0, "validBelow": 0, "validAbove": 0}) is False


async def test_timeout_fallback_arms():
    base = {"allNew": 2, "src": "https://a/b.png", "reason": "waiting"}
    got = await ow._handle_timeout_fallback(dict(base), 30.0, lambda m: None)
    assert got and got["ready"] is True and got["fallback"] is True
    assert await ow._handle_timeout_fallback(
        {"reason": "job_id_mismatch_no_matching_image"}, 30.0, lambda m: None) is None
    assert await ow._handle_timeout_fallback(
        {**base, "mismatchDetails": [{"a": 1}]}, 30.0, lambda m: None) is None
    assert await ow._handle_timeout_fallback(
        {**base, "expectedJobId": "e", "associatedJobId": "x"}, 30.0, lambda m: None) is None
    assert await ow._handle_timeout_fallback({"allNew": 2}, 30.0, lambda m: None) is None  # no src


async def test_wait_loop_logging_handlers():
    out = logs()
    await ow.handle_spinner_visible({"spinDetails": [{"label": "gen"}]}, out.append)
    assert any("gen" in m for m in out)
    await ow.handle_spinner_visible({}, out.append)
    await ow.handle_spinner_visible({"spinDetails": "bad"}, out.append)  # exception arm
    assert any("Spinner visible" in m for m in out)

    out = logs()
    await ow.handle_spinner_gone(out.append)
    assert out

    out = logs()
    await ow.handle_ready_result({"associatedJobId": "x", "expectedJobId": "e"}, out.append)
    assert any("mismatch before download" in m for m in out)
    await ow.handle_ready_result({"associatedJobId": "e", "expectedJobId": "e",
                                  "layoutReverse": True, "orderCheck": "ok"}, out.append)
    assert any("verified" in m for m in out)
    await ow.handle_ready_result("not a dict", out.append)  # exception arm
    assert any("waiting 3s" in m for m in out)

    out = logs()
    await ow.handle_no_exact_below(
        {"reason": "job_id_mismatch", "expectedJobId": "e",
         "mismatchDetails": [{"associated": "a"}, {"associated": "b"}]}, out.append)
    assert any("found images belong to a,b" in m for m in out)
    await ow.handle_no_exact_below({"reason": "waiting", "jobTop": 1}, out.append)
    assert any("No exact below" in m for m in out)
    await ow.handle_no_exact_below("bad", out.append)
    assert any("Waiting for image below" in m for m in out)

    out = logs()
    await ow.handle_mismatch({"expectedJobId": "e", "mismatchDetails": [{"a": 1}],
                              "poolDetails": [{"p": 1}]}, out.append)
    assert any("Strict verification failed" in m for m in out)
    await ow.handle_mismatch("bad", out.append)
    assert any("not downloading incorrect image" in m for m in out[-1:])


async def test_poll_check_success_error_and_abort():
    async def ok_check():
        return {"ready": True, "src": "s"}
    diag, err = await ow._poll_check(ok_check, 0.01)
    assert diag["ready"] is True and err is None

    async def bad_check():
        raise RuntimeError("poll down")
    diag, err = await ow._poll_check(bad_check, 0.01)
    assert diag is None and err["reason"] == "poll down"

    async def abort_check():
        raise PageErrorAbort("limit")
    with pytest.raises(PageErrorAbort):
        await ow._poll_check(abort_check, 0.01)
