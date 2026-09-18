"""CAPTCHA_JOB join lines — stash drain at image-job end.

RULE 8: the real runner helpers against a stub ctx (records bridge
logs). Each stashed encounter yields exactly one join line carrying
the job outcome + page error, then the stash drains.
"""

import json
from types import SimpleNamespace

import pytest

from app.services.single_job_runner import (
    _captcha_job_line,
    _emit_captcha_job_lines,
    _reset_captcha_reports,
)


def stub_ctx(entries):
    logs = []
    ctx = SimpleNamespace(
        ctrl=SimpleNamespace(_captcha_reports=list(entries)),
        bridge=SimpleNamespace(_log=lambda m, l="info": logs.append((m, l))),
        corr_id="corr-1",
        tab_id="tabA",
        img=SimpleNamespace(relative_path="icons/a.png"),
    )
    return ctx, logs


def job_lines(logs):
    return [json.loads(m.split("🧾 CAPTCHA_JOB ", 1)[1])
            for m, _ in logs if "🧾 CAPTCHA_JOB " in m]


@pytest.mark.unit
def test_failed_job_with_page_error_joins():
    ctx, logs = stub_ctx([{"eid": "abc123", "tab": "tabA"}])
    err = "Wait failed: Page error: Something went wrong. Trace ID: 1"
    _emit_captcha_job_lines(ctx, True, err)
    lines = job_lines(logs)
    assert len(lines) == 1
    line = lines[0]
    assert line["eid"] == "abc123" and line["corr"] == "corr-1"
    assert line["tab"] == "tabA" and line["image"] == "icons/a.png"
    assert line["job"] == "failed"
    assert "Something went wrong" in line["page_error"]
    assert ctx.ctrl._captcha_reports == []  # drained
    _emit_captcha_job_lines(ctx, True, err)
    assert len(job_lines(logs)) == 1  # each eid reported exactly once


@pytest.mark.unit
def test_completed_job_clears_page_error():
    ctx, logs = stub_ctx([{"eid": "e1", "tab": "tabA"}, {"eid": "e2", "tab": "tabA"}])
    _emit_captcha_job_lines(ctx, False, "")
    lines = job_lines(logs)
    assert [l["eid"] for l in lines] == ["e1", "e2"]
    assert all(l["job"] == "completed" and l["page_error"] == "" for l in lines)


@pytest.mark.unit
def test_missing_or_malformed_stash_is_silent_or_safe():
    ctx, logs = stub_ctx([])
    ctx.ctrl = SimpleNamespace()  # never stashed: silent
    _emit_captcha_job_lines(ctx, True, "boom")
    assert job_lines(logs) == []
    ctx2, logs2 = stub_ctx(["oops", {}])  # malformed: tolerated
    _emit_captcha_job_lines(ctx2, True, "boom")
    assert len(job_lines(logs2)) == 2


@pytest.mark.unit
def test_reset_drops_stale_entries():
    ctx, _ = stub_ctx([{"eid": "stale", "tab": "tabA"}])
    _reset_captcha_reports(ctx)
    assert ctx.ctrl._captcha_reports == []


@pytest.mark.unit
def test_job_line_truncates_long_errors():
    ctx, _ = stub_ctx([])
    line = _captcha_job_line(ctx, {"eid": "e", "tab": "t"}, True, "x" * 500)
    assert len(line["error"]) == 200
