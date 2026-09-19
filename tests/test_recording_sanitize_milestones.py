"""D5 mutation triage: recording sanitize + milestones, branch-complete.

Targets sanitize (textual_mime 7, redact_text 6, safe_url 5, clean_mapping 3,
contains_tokenish 1) and milestones (assert_token_free 8, build_milestone 2).
"""

from types import SimpleNamespace

from app.services.captcha_recording.milestones import (
    MILESTONE_PHASES,
    assert_token_free,
    build_milestone,
)
from app.services.captcha_recording.sanitize import (
    MAX_TEXT,
    clean_mapping,
    contains_tokenish,
    redact_text,
    safe_url,
    textual_mime,
)


class TestSafeUrl:
    def test_strips_query(self):
        assert safe_url("https://x.test/a/b?api_key=SECRET&t=1") == "https://x.test/a/b"

    def test_strips_fragment(self):
        assert safe_url("https://x.test/a#tok") == "https://x.test/a"

    def test_keeps_port(self):
        assert safe_url("http://x.test:8080/p") == "http://x.test:8080/p"

    def test_ipv6_bracketed(self):
        assert safe_url("http://[::1]:9000/p") == "http://[::1]:9000/p"

    def test_empty_and_none(self):
        assert safe_url("") == ""
        assert safe_url(None) == ""

    def test_no_scheme(self):
        assert safe_url("x.test/a?q=1") == "x.test/a"

    def test_broken_returns_empty(self):
        assert safe_url("http://[::1") == ""


class TestRedactText:
    def test_bearer(self):
        out = redact_text("Authorization: Bearer abc.def-123")
        assert "abc.def-123" not in out
        assert "[REDACTED_BEARER]" in out

    def test_long_opaque_token(self):
        token = "A" * 80
        out = redact_text(f"token={token} done")
        assert token not in out
        assert "[REDACTED_TOKEN]" in out

    def test_short_strings_untouched(self):
        assert redact_text("normal text 123") == "normal text 123"

    def test_limit(self):
        assert redact_text("x" * 100, limit=10) == "x" * 10
        assert redact_text("x" * 100, limit=0) == ""
        assert redact_text("x" * 100, limit=-5) == ""

    def test_none(self):
        assert redact_text(None) == ""

    def test_truncates_at_max(self):
        # space-separated so the bulk is not token-shaped
        text = "y " * (MAX_TEXT // 2 + 50)
        assert len(redact_text(text)) == MAX_TEXT


class TestCleanMapping:
    def test_secret_key_with_credential(self):
        out = clean_mapping({"token": "A" * 40, "note": "ok"})
        assert out["token"] == "[REDACTED]"
        assert out["note"] == "ok"

    def test_secret_key_with_timing_survives(self):
        # S-1: int timings and short status words are evidence, not secrets
        out = clean_mapping({"token_visible_at_ms": 1234, "state": "visible"})
        assert out["token_visible_at_ms"] == 1234
        assert out["state"] == "visible"

    def test_secret_key_with_bearer_survives_shape(self):
        out = clean_mapping({"cookie": "Bearer zzz"})
        assert out["cookie"] == "[REDACTED]"

    def test_plain_secret_named_key_non_credential(self):
        out = clean_mapping({"secret": "short"})
        assert out["secret"] == "short"

    def test_nested(self):
        data = {"a": [{"b": {"password": "x" * 30}}], "c": [1, 2]}
        out = clean_mapping(data)
        assert out["a"][0]["b"]["password"] == "[REDACTED]"
        assert out["c"] == [1, 2]

    def test_strings_redacted(self):
        out = clean_mapping({"text": "Bearer abc"})
        assert out["text"] == "[REDACTED_BEARER]"

    def test_scalar_passthrough(self):
        assert clean_mapping(5) == 5
        assert clean_mapping(None) is None
        assert clean_mapping(True) is True


class TestTextualMime:
    def test_variants(self):
        assert textual_mime("text/html") is True
        assert textual_mime("application/json") is True
        assert textual_mime("text/xml") is True
        assert textual_mime("application/javascript") is True
        assert textual_mime("image/png") is False
        assert textual_mime("") is False
        assert textual_mime(None) is False

    def test_case(self):
        assert textual_mime("TEXT/HTML") is True


class TestContainsTokenish:
    def test_variants(self):
        assert contains_tokenish("Bearer abc123") is True
        assert contains_tokenish("A" * 80) is True
        assert contains_tokenish("hello world") is False
        assert contains_tokenish("") is False
        assert contains_tokenish(None) is False


LONG_TOKEN = "T" * 80


class TestAssertTokenFree:
    def test_clean_passes(self):
        assert_token_free({"status": "solved", "reason": "accepted"})
        assert_token_free([1, 2, "ok"])

    def test_bearer_raises(self):
        try:
            assert_token_free({"x": "Bearer abc"})
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_long_token_raises(self):
        try:
            assert_token_free({"x": LONG_TOKEN})
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestBuildMilestone:
    def test_unknown_phase_raises(self):
        try:
            build_milestone("nope", SimpleNamespace(), offset_ms=1)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_final_fields(self):
        outcome = SimpleNamespace(
            status="solved", reason="accepted", method="auto", task_id="t-1",
            polls=3, attempts=2, elapsed_sec=12.5, token_sec=1.25,
            dialog_at_token="div", inject="ok", continue_result="fine",
            page_error_at_s=None, page_error=None, task_created_sec=0.5,
            dialog_cleared_sec=9, page_identity="p1", challenge_identity="c1",
            secret_attr="should not appear",
        )
        payload = build_milestone("final", outcome, offset_ms=42)
        assert payload["phase"] == "final"
        assert payload["offset_ms"] == 42
        assert payload["status"] == "solved"
        assert payload["polls"] == 3
        assert payload["attempts"] == 2
        assert payload["token_sec_ms"] == 1250
        assert payload["elapsed_sec_ms"] == 12500
        assert payload["task_created_sec_ms"] == 500
        assert payload["dialog_cleared_sec_ms"] == 9000
        assert "secret_attr" not in payload
        assert "page_error" not in payload  # None skipped

    def test_missing_attrs_skipped(self):
        payload = build_milestone("final", SimpleNamespace(), offset_ms=1)
        assert payload == {"phase": "final", "offset_ms": 1}

    def test_empty_string_skipped(self):
        payload = build_milestone("final", SimpleNamespace(status="", reason="ok"), offset_ms=1)
        assert "status" not in payload
        assert payload["reason"] == "ok"

    def test_string_bounded(self):
        # space-separated: 300 chars that are not credential-shaped
        outcome = SimpleNamespace(reason="r " * 150)
        payload = build_milestone("final", outcome, offset_ms=1)
        assert len(payload["reason"]) == 200

    def test_float_bounded(self):
        payload = build_milestone("token_ready",
                                  SimpleNamespace(task_id="t", token_sec=1.23456), offset_ms=1)
        assert payload["token_sec_ms"] == 1235

    def test_tokenish_fails_closed(self):
        outcome = SimpleNamespace(reason=f"got {LONG_TOKEN}")
        try:
            build_milestone("final", outcome, offset_ms=1)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_all_phases_buildable(self):
        for phase in MILESTONE_PHASES:
            payload = build_milestone(phase, SimpleNamespace(), offset_ms=0)
            assert payload["phase"] == phase
