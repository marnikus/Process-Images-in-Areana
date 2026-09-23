"""The savelog contract — line 1 is the verdict, and waiting has named ends.

`parse_status` reads Ui.Vision's own file format (`Status=OK` / `Status=Error:`
+ `###` + log); `poll_log` distinguishes answered / timeout / stopped / corrupt
(RULE 4 — never one invented "failed") and honours the stop seam (RULE 7).
"""

import time

import pytest

from app.browser.uivision import logread
from app.browser.uivision.logread import LogResult, parse_status, poll_log

pytestmark = pytest.mark.unit

OK_FILE = "Status=OK\n###\necho: done — XClick fired (native OS input)\nLog loaded: 1 lines"
ERR_FILE = "Status=Error: XClick failed: image not found\n###\n[XClick] target missing"


# ── parse_status ─────────────────────────────────────────────────────────────

def test_empty_or_missing_content_is_still_waiting():
    assert parse_status("") is None
    assert parse_status("   \n ") is None
    assert parse_status(None) is None


def test_ok_and_error_verdicts():
    ok = parse_status(OK_FILE)
    assert (ok.kind, ok.done) == ("ok", True)
    assert ok.message == "macro completed"
    assert ok.lines[0].startswith("echo: done")
    assert "###" not in ok.lines and not any(line.startswith("Status=") for line in ok.lines)
    err = parse_status(ERR_FILE)
    assert (err.kind, err.done, err.message) == ("error", True, "XClick failed: image not found")


def test_unreadable_first_line_is_corrupt_not_failed():
    got = parse_status("garbage line\n###\nsomething")
    assert got.kind == "corrupt" and got.done is False
    assert "garbage line" in got.message


def test_log_tail_is_capped_and_keeps_the_last_lines():
    rows = "\n".join(f"line {n}" for n in range(1, 71))
    got = parse_status(f"Status=OK\n###\n{rows}")
    assert len(got.lines) == logread.MAX_LINES == 60
    assert got.lines[-1] == "line 70" and got.lines[0] == "line 11"


# ── poll_log ─────────────────────────────────────────────────────────────────

async def test_poll_returns_the_verdict_without_sleeping(tmp_path):
    log = tmp_path / "run.txt"
    log.write_text(OK_FILE, encoding="utf-8")
    naps = []

    async def sleep(sec):
        naps.append(sec)

    got = await poll_log(log, time.time() + 30, sleep=sleep)
    assert got.kind == "ok" and naps == []


async def test_poll_timeout_names_the_deadline(tmp_path):
    got = await poll_log(tmp_path / "never.txt", time.time() - 1)
    assert got.kind == "timeout"
    assert "deadline" in got.message and "never.txt" in got.message


async def test_poll_stop_wins_over_waiting(tmp_path):
    got = await poll_log(tmp_path / "never.txt", time.time() + 60, stop=lambda: True)
    assert got.kind == "stopped" and "log file" in got.message


async def test_poll_waits_until_the_extension_answers(tmp_path):
    log = tmp_path / "run.txt"
    naps = []

    async def sleep(sec):
        naps.append(sec)
        if len(naps) == 2:                     # the file lands during the wait
            log.write_text(ERR_FILE, encoding="utf-8")

    got = await poll_log(log, time.time() + 30, sleep=sleep)
    assert got.kind == "error"
    assert naps == [logread.POLL_SECONDS] * 2


def test_log_result_defaults():
    row = LogResult(kind="timeout")
    assert (row.message, row.lines, row.done) == ("", (), False)
