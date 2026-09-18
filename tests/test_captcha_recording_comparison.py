"""Comparison identifies shared evidence and the first ordered divergence."""

import pytest

from app.services.captcha_recording.comparison import RecordingComparison


def details(actor, result, events, html):
    return {"manifest": {"session_id": actor, "actor_label": actor,
                         "result_label": result, "truncated": []},
            "events": events, "latest_snapshot": {"html": html},
            "evidence_complete": True}


def event(offset, state):
    return {"offset_ms": offset, "kind": "state", "payload": {"state": state}}


@pytest.mark.unit
def test_comparison_reports_common_and_first_divergence():
    manual = details("manual", "passed", [event(0, "detected"), event(10, "accepted")],
                     "<main><b>accepted</b></main>")
    bot = details("bot", "failed", [event(0, "detected"), event(20, "page_error")],
                  "<main><b>failed</b></main>")

    report = RecordingComparison().compare(manual, bot)

    assert "state|detected|||" in report["common"]
    assert report["first_divergence"]["operation"] == "replace"
    assert any("accepted" in line or "failed" in line for line in report["dom_diff"])
    assert report["evidence_complete"] is True


@pytest.mark.unit
def test_comparison_warns_for_unknown_or_truncated_evidence():
    left = details("unknown", "unknown", [], "")
    left["manifest"]["truncated"] = ["events"]
    left["evidence_complete"] = False
    report = RecordingComparison().compare(left, details("bot", "failed", [], ""))
    assert report["evidence_complete"] is False
    assert len(report["warnings"]) == 3
