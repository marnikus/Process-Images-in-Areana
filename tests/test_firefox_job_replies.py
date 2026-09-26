"""Reading a savelog back: the ARENA_* markers, the verdicts, the correlation.

The macro's only channel is the case log, so every phase writes one `echo` per
answer (`ARENA_STATE=<json>`, `ARENA_ATTACH=<json>`, …) and this module is the
one reader. Its rules are the job's honesty rules: an attachment needs exactly
one NEW tile matching the sent file; a prompt needs read-back equality and a
matching FNV-1a hash; a result is `ready` only when it is new, after this job's
own `[JOB-ID: …]` message and not part of it — anything else is a named doubt,
never a `completed`.

RED at base: `app/browser/uivision/job_replies.py` did not exist.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.browser.uivision import job_replies as jr

pytestmark = pytest.mark.unit

PROMPT = "héllo\nworld 🎨"


def line(mark, value):
    return f"echo: {mark}{json.dumps(value, ensure_ascii=False)}"


def text_line(mark, value):
    return f"echo: {mark}{value}"


def test_parse_reads_every_marker_and_the_last_occurrence_wins():
    lines = [
        line(jr.STATE_MARK, {"clean": False, "composer": {"len": 3}}),
        line(jr.STATE2_MARK, {"clean": True}),
        line(jr.ATTACH_MARK, {"ok": False, "reason": "no attachment preview"}),
        line(jr.ATTACH_MARK, {"ok": True, "found": {"alt": "a.png"}}),
        text_line(jr.ATTACH_SEL_MARK, "xpath=/html[1]/body[1]/button[2]"),
        text_line(jr.REMOVE_SEL_MARK, "xpath=/html[1]/button[1]"),
        line(jr.PROMPT_MARK, {"ok": True, "len": 4, "hash": "deadbeef"}),
        text_line(jr.GUARD_MARK, "false"),
        text_line(jr.WHY_MARK, "send button disabled"),
        text_line(jr.SEND_SEL_MARK, "xpath=/html[1]/button[9]"),
        text_line(jr.SUBMIT_MARK, "1"),
        line(jr.RESULT_MARK, {"ok": True, "candidates": [{"src": "https://x/1.png"}]}),
        line(jr.DATA_MARK, {"ok": True, "b64": "aGk=", "len": 4}),
        text_line(jr.NEWCHAT_SEL_MARK, "xpath=/html[1]/a[1]"),
    ]
    got = jr.parse(lines)
    assert got.state["composer"]["len"] == 3 and got.state2["clean"] is True
    assert got.attach["found"]["alt"] == "a.png"          # the later answer wins
    assert got.attach_sel.startswith("xpath=/")
    assert got.remove_sel.endswith("button[1]")
    assert got.prompt["hash"] == "deadbeef"
    assert got.guard == "false" and got.guard_why == "send button disabled"
    assert got.send_sel.endswith("button[9]")
    assert got.submit == "1"
    assert got.result["ok"] and got.data["b64"] == "aGk="
    assert got.newchat_sel.endswith("a[1]")
    assert got.answered is True
    assert jr.parse([]).answered is False


def test_torn_and_foreign_lines_are_skipped_never_guessed():
    """An unrendered `${var}` echo and a foreign marker must not become an answer."""
    lines = ["echo: ARENA_PROMPT=${arenaPrompt}",
             "echo: ARENA_ATTACH=not json at all",
             "some other log line: ARENA_GUARD=maybe"]
    got = jr.parse(lines)
    assert got.prompt == {} and got.attach == {}      # both JSON answers are unusable
    assert got.guard == "maybe"                       # a text marker is whatever follows it
    assert jr.parse(["echo: ARENA_PROMPT=${arenaPrompt}"]).answered is False
    assert jr.guard_verdict(got.guard, got.guard_why)[0] is False   # …and never a pass


def test_prompt_hash_matches_the_pages_fnv1a_over_utf16():
    assert jr.prompt_hash("hello") == "c3457ef7"
    assert jr.prompt_hash("héllo") == "140887eb"
    assert jr.prompt_hash("héllo\nworld [JOB-ID: 7]") == "73974617"
    assert jr.prompt_hash("日本語 🎨 multi\nline") == "a8e68882"
    assert jr.prompt_hash("") == "811c9dc5"


def test_attach_verdict_needs_one_new_matching_tile():
    ok, reason = jr.attach_verdict({"ok": True, "found": {"alt": "a.png"}}, cleaned=True)
    assert ok and "a.png" in reason and "dropped" in reason
    ok, reason = jr.attach_verdict({"ok": False, "reason": "stale attachment from a previous job (b.png)"})
    assert not ok and "stale attachment" in reason
    ok, reason = jr.attach_verdict({})
    assert not ok and "no attachment answer" in reason
    ok, reason = jr.attach_verdict({"security": True, "ok": False})
    assert not ok and "manual action" in reason


def test_prompt_verdict_catches_truncation_and_duplication():
    want = jr.prompt_hash(PROMPT)
    ok, reason = jr.prompt_verdict({"ok": True, "len": len(PROMPT), "hash": want,
                                    "expected_hash": want, "occurrences": 1}, want)
    assert ok and "read-back matched" in reason
    ok, reason = jr.prompt_verdict({"ok": False, "reason": "truncated read-back", "len": 3,
                                    "expected_len": len(PROMPT), "hash": jr.prompt_hash(PROMPT[:3]),
                                    "occurrences": 0}, want)
    assert not ok and "truncated read-back" in reason and "hash" in reason
    ok, reason = jr.prompt_verdict({"ok": False, "reason": "read-back differs", "len": len(PROMPT) * 2,
                                    "expected_len": len(PROMPT), "hash": "0",
                                    "occurrences": 2}, want)
    assert not ok and "2 occurrence(s)" in reason
    assert jr.prompt_verdict({})[0] is False


def test_guard_verdict_and_submit_count():
    assert jr.guard_verdict("true")[0] is True
    assert jr.guard_verdict("false", "prompt read-back differs (3/9 chars)")[1] == \
        "prompt read-back differs (3/9 chars)"
    assert "did not answer" in jr.guard_verdict("false", "")[1]
    assert "did not answer" in jr.guard_verdict("", "ready")[1]
    assert jr.submit_count("1") == 1 and jr.submit_count("x") == 0 and jr.submit_count("") == 0
    assert jr.submitted(jr.parse([text_line(jr.SUBMIT_MARK, "1")])) == (True, "submit click recorded (x1)")
    lost = jr.parse([line(jr.RESULT_MARK, {"token_seen": True})])
    assert jr.submitted(lost) == (True, "prompt token seen on the page (click acknowledgment lost)")
    assert jr.submitted(jr.parse([]))[0] is False


def test_locate_verdict_only_accepts_an_xpath_the_extension_can_click():
    assert jr.locate_verdict("xpath=/html[1]/body[1]/button[2]") == \
        ("xpath=/html[1]/body[1]/button[2]", True)
    assert jr.locate_verdict("none") == ("", False)
    assert jr.locate_verdict("") == ("", False)
    assert jr.locate_verdict("button[aria-label='Send']") == ("", False)


def test_bytes_from_decodes_and_checks_the_declared_length():
    data = b"\x89PNG\r\n\x1a\n" + b"0" * 120
    b64 = base64.b64encode(data).decode()
    ok, raw, note = jr.bytes_from({"ok": True, "b64": b64, "len": len(b64), "method": "fetch"})
    assert ok and raw == data and f"{len(data)} bytes via fetch" in note
    ok, raw, note = jr.bytes_from({"ok": True, "b64": b64, "len": len(b64) + 5})
    assert not ok and "announced" in note
    assert jr.bytes_from({"ok": False, "note": "status 403"}) == (False, b"", "status 403")
    assert jr.bytes_from({})[0] is False
    assert jr.bytes_from({"ok": True, "b64": "%%%"})[0] is False


def test_correlate_prefers_the_largest_candidate_after_this_jobs_own_message():
    ready = {"candidates": [{"src": "https://x/1.png", "after": True, "in_user": False,
                             "large": True, "nat": 900, "w": 400}]}
    assert jr.correlate(ready) == ("ready", "https://x/1.png",
                                   "one large candidate after this job's token")
    one_large = {"candidates": [{"src": "https://x/1.png", "after": True, "large": True, "nat": 900},
                                {"src": "https://x/icon.png", "after": True, "large": False, "nat": 16}]}
    assert jr.correlate(one_large)[0] == "ready"      # icons beside the result are not doubt
    two = {"candidates": [{"src": "https://x/1.png", "after": True, "large": True, "nat": 900},
                          {"src": "https://x/2.png", "after": True, "large": True, "nat": 700}]}
    status, src, reason = jr.correlate(two)
    assert status == "ambiguous" and src == "https://x/1.png" and "2 candidate(s)" in reason
    own = {"candidates": [{"src": "blob:https://x/me", "after": False, "in_user": True,
                           "large": True, "nat": 900}]}
    status, _src, reason = jr.correlate(own)
    assert status == "rejected" and "older result was rejected" in reason
    assert jr.correlate({"timed_out": True, "token_seen": True})[0] == "uncertain"
    assert jr.correlate({"timed_out": True, "token_seen": False})[0] == "missing"
    assert jr.correlate({"spinning": True})[0] == "uncertain"
    assert jr.correlate({"security": True})[0] == "uncertain"
    assert jr.correlate({"timed_out": True, "token_seen": True, "candidates": [
        {"src": "https://x/old.png", "after": False, "in_user": False, "large": True}]})[0] == "rejected"
    assert jr.correlate({})[0] == "missing" and jr.correlate({})[2].startswith("no result answer")


def test_a_delayed_result_from_a_previous_job_can_never_be_taken():
    """The baseline holds every src the page had before this job: nothing old is 'new'."""
    reply = {"candidates": [{"src": "https://x/old.png", "after": True, "in_user": False,
                             "large": True, "baseline": True}]}
    assert jr.correlate(reply)[0] == "ready"      # the probe filters baselines before reporting
    assert jr.correlate({})[0] == "missing"


def test_previews_and_baseline_are_read_from_the_later_state_when_it_exists():
    replies = jr.parse([line(jr.STATE_MARK, {"previews": [{"alt": "a"}], "srcs": ["s1"]}),
                        line(jr.STATE2_MARK, {"previews": [], "srcs": ["s2", "s1"]})])
    assert jr.previews_of(replies) == []
    assert jr.baseline_of(replies) == ["s2", "s1"]
    assert jr.preview_key({"alt": "a", "src": "b"}) == "a|b"


def test_clean_verdict_needs_the_whole_clean_page():
    ok, reason = jr.clean_verdict({"clean": True})
    assert ok and "composer empty" in reason
    assert jr.clean_verdict({})[0] is False
    assert "composer not found" in jr.clean_verdict({"textarea": False})[1]
    assert "security" in jr.clean_verdict({"textarea": True, "security": True})[1]
    assert "generation" in jr.clean_verdict({"textarea": True, "spinning": True})[1]
    assert "attachment(s) still" in jr.clean_verdict({"textarea": True, "previews": [{}]})[1]
    assert "not empty" in jr.clean_verdict({"textarea": True, "composer": {"len": 5}})[1]
