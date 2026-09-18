"""Comparison aligns named edges and reports the first real divergence."""

import pytest

from app.services.captcha_recording.comparison import RecordingComparison


def details(actor, result, events, html, edges=()):
    return {"manifest": {"session_id": actor, "actor_label": actor,
                         "result_label": result, "truncated": []},
            "events": events, "milestones": list(edges),
            "latest_snapshot": {"html": html}, "evidence_complete": True}


def state_event(offset, state):
    return {"offset_ms": offset, "kind": "state", "payload": {"state": state}}


def edge(offset, phase):
    return {"offset_ms": offset, "phase": phase}


@pytest.mark.unit
def test_comparison_aligns_edges_and_reports_first_divergence():
    manual = details("manual", "passed", [state_event(0, "detected")],
                     "<main><b>accepted</b></main>",
                     [edge(0, "detected"), edge(12_000, "dialog_cleared")])
    bot = details("bot", "failed", [state_event(0, "detected")],
                  "<main><b>failed</b></main>",
                  [edge(0, "detected"), edge(11_000, "page_error")])

    report = RecordingComparison().compare(manual, bot)

    assert "state|detected" in report["common"]
    assert report["verdict"]["comparable"] is True
    assert report["first_divergence"]["phase"] == "page_error"
    assert report["first_divergence"]["status"] == "b_only"
    assert any("accepted" in line or "failed" in line for line in report["dom_diff"])
    assert report["evidence_complete"] is True
    assert report["warnings"] == []


@pytest.mark.unit
def test_comparison_refuses_unknown_labels_and_surfaces_side_warnings():
    left = details("unknown", "unknown", [], "")
    left["warnings"] = ["events truncated"]
    left["evidence_complete"] = False

    report = RecordingComparison().compare(left, details("bot", "failed", [], ""))

    assert report["evidence_complete"] is False
    assert report["verdict"]["comparable"] is False
    assert "label both sessions" in report["verdict"]["reason"]
    assert report["warnings"] == ["left: events truncated"]
