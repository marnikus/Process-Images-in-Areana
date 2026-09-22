"""I-65 · reading the Ui.Vision log — the only completion signal there is.

The distinction that matters: a log with no verdict yet means **still
running**, not failed. Conflating the two would make every slow macro look
broken and would end the poll early.
"""

import pytest

from app.browser.uivision.run_log import (FAILED, OK, PENDING, clear_log, parse_log,
                                          read_verdict)


class TestParse:
    def test_status_ok_is_success(self):
        assert parse_log("[status] Macro completed").state == OK

    def test_status_equals_ok_is_success(self):
        assert parse_log("Status=OK").state == OK

    def test_an_error_line_is_failure(self):
        assert parse_log("[error] element not found").state == FAILED

    def test_status_error_is_failure(self):
        assert parse_log("Status=Error").state == FAILED

    def test_a_log_without_a_verdict_is_still_running(self):
        # the macro has started but not finished — polling must continue
        assert parse_log("[info] opening https://arena.ai/").state == PENDING

    def test_an_empty_log_is_still_running(self):
        assert parse_log("").state == PENDING and parse_log("   \n\n").state == PENDING

    def test_the_last_verdict_wins(self):
        # Ui.Vision writes the verdict last; an early [error] from a retried
        # step must not mask a successful finish
        assert parse_log("[error] retrying\n[status] Macro completed").state == OK

    def test_failure_after_success_is_failure(self):
        assert parse_log("[status] Macro completed\n[error] later boom").state == FAILED

    def test_the_verdict_line_is_reported(self):
        assert "not found" in parse_log("[error] not found").message

    def test_blank_lines_are_dropped_from_the_tail(self):
        assert parse_log("a\n\n\nb").lines == ["a", "b"]

    def test_is_done_only_for_a_verdict(self):
        assert parse_log("[status] Macro completed").is_done
        assert not parse_log("[info] running").is_done

    def test_ok_is_only_true_for_success(self):
        assert parse_log("Status=OK").ok and not parse_log("[error] x").ok


class TestReadVerdict:
    def test_a_missing_log_is_pending_not_an_error(self, tmp_path):
        # before the macro writes anything, the file simply does not exist
        verdict = read_verdict(tmp_path / "never-written.txt")
        assert verdict.state == PENDING and not verdict.is_done

    def test_a_written_log_is_read(self, tmp_path):
        log = tmp_path / "uiv.log"
        log.write_text("[status] Macro completed", encoding="utf-8")
        assert read_verdict(log).ok

    def test_a_directory_instead_of_a_file_is_pending_not_a_crash(self, tmp_path):
        assert read_verdict(tmp_path).state == PENDING

    def test_undecodable_bytes_do_not_raise(self, tmp_path):
        log = tmp_path / "uiv.log"
        log.write_bytes(b"\xff\xfe[status] Macro completed")
        assert read_verdict(log).ok

    def test_an_empty_path_is_pending(self):
        assert read_verdict("").state == PENDING


class TestClearLog:
    def test_a_stale_log_is_removed(self, tmp_path):
        # otherwise the poller reads the *previous* run's verdict instantly
        log = tmp_path / "uiv.log"
        log.write_text("[status] Macro completed", encoding="utf-8")
        assert clear_log(log) and not log.exists()

    def test_clearing_an_absent_log_succeeds(self, tmp_path):
        assert clear_log(tmp_path / "nope.txt")

    def test_an_empty_path_cannot_be_cleared(self):
        # no log path means no verdict is possible — the caller must not run
        assert clear_log("") is False

    def test_an_unremovable_path_reports_failure(self, tmp_path):
        assert clear_log(tmp_path) is False  # a directory cannot be unlinked


class TestBlankLines:
    def test_a_whitespace_only_line_is_not_a_verdict(self):
        # parse_log filters blanks, but _verdict_of must be safe on its own
        from app.browser.uivision.run_log import _verdict_of
        assert _verdict_of("   ") is None and _verdict_of("") is None
