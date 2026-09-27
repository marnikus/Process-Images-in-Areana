"""A timed-out output wait says what the probe saw last (I-69, 2026-09-27).

Owner log: `✖ output_detected — Wait failed: Timeout after 120000ms` while the
image was on the page. The last probe answer (`generating_spinner_visible`,
caused by a sidebar spinner) was in the result but never reached the log, so
the report could not show why. RULE 4: an honest failure names its cause.
"""

import pytest

from app.browser.cdp_arena.output import _timeout_text

pytestmark = pytest.mark.unit


def test_the_last_probe_reason_and_spinner_labels_are_named():
    last = {"reason": "generating_spinner_visible", "spinDetails": [{"label": "Max"}, {"label": "Response B"}]}
    assert _timeout_text({"reason": "timeout", "last": last}, 120000) == (
        "Timeout after 120000ms — last check: generating_spinner_visible (spinner: Max, Response B)")


def test_a_reason_without_spinners_is_named_alone():
    last = {"reason": "no_new", "spinDetails": []}
    assert _timeout_text({"last": last}, 5000) == "Timeout after 5000ms — last check: no_new"


def test_no_last_answer_keeps_the_plain_text_and_the_pause_note():
    assert _timeout_text({}, 400) == "Timeout after 400ms"
    assert _timeout_text({"pause_note": "captcha wait 12s", "last": {"reason": "not_started"}}, 400) == (
        "Timeout after 400ms — last check: not_started (captcha wait 12s)")


def test_a_mismatch_result_is_its_own_last_answer():
    """`_check_timeout` returns the mismatch diag itself (no `last` key)."""
    res = {"reason": "job_id_mismatch_no_matching_image", "elapsed": 121.0}
    assert _timeout_text(res, 120000) == "Timeout after 120000ms — last check: job_id_mismatch_no_matching_image"
