"""core.run_scope — the one run-scope predicate and its claim-time re-check (B13, I-44).

RULE 8: the aliases in the panels/services are exercised through their real
modules so a re-introduced private copy would be caught here.
"""

from types import SimpleNamespace

import pytest

from app.core import run_scope as rsc
from app.core.enums import ImageStatus
from app.ui.panels import queue_scan, run_control


def img(name="a.png", status="pending", selected=True):
    return SimpleNamespace(relative_path=name, status=status, selected=selected)


@pytest.mark.parametrize("status,expected", [
    ("pending", True), ("selected", True), ("failed", True),
    ("needs_review", True), ("processing", True),
    ("completed", False), ("skipped", False), ("deselected", False),
    ("", False), ("bogus", False),
])
def test_is_runnable_table(status, expected):
    assert rsc.is_runnable(status) is expected


def test_every_image_status_has_a_verdict():
    """A new ImageStatus member must be placed on one side explicitly."""
    known = rsc.RUNNABLE_STATUSES | {"completed", "skipped", "deselected"}
    assert {s.value for s in ImageStatus} == known


def test_run_scope_requires_selected_and_runnable():
    items = [img("a", "pending", True), img("b", "completed", True), img("c", "pending", False),
             img("d", "failed", True), img("e", "skipped", True), img("f", "processing", True)]
    assert [i.relative_path for i in rsc.run_scope(items)] == ["a", "d", "f"]
    assert rsc.run_scope([]) == []


def test_run_panel_filters_with_the_core_predicate():
    items = [img("a", "pending", True), img("b", "completed", True), img("c", "needs_review", True)]
    assert run_control.run_scope is rsc.run_scope, "one predicate — no panel-level alias (RULE 18.1)"
    assert not hasattr(queue_scan, "selected_images")
    assert [i.relative_path for i in run_control.run_scope(items)] == ["a", "c"]


def test_claim_denied_logs_once_for_settled_only():
    lines = []
    log = lambda m, level="info": lines.append((m, level))  # noqa: E731
    assert rsc.claim_denied(img("ok.png", "pending"), log) is False
    assert rsc.claim_denied(img("retry.png", "failed"), log) is False
    assert lines == []
    assert rsc.claim_denied(img("done.png", "completed"), log) is True
    assert rsc.claim_denied(img("gone.png", "skipped"), log) is True
    assert lines == [("⏭ Skipping done.png — already completed", "info"),
                     ("⏭ Skipping gone.png — already skipped", "info")]
