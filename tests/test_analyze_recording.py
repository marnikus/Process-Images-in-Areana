"""analyze_captcha_recording.py — evidence-gated classification (RULE 8)."""

import json
from pathlib import Path

import pytest

from tools.analyze_captcha_recording import _classify, _find_session_folders, analyze


def _session(folder: Path, manifest: dict, events: list[dict] | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if events is not None:
        (folder / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def _state(token_ms=40000, dialog="visible", inject="scope=dialog fields=1 cb=called via anchor"):
    return {"seq": 1, "kind": "state", "state": "auto_attempt_finished",
            "token_at_ms": token_ms, "dialog_at_token": dialog, "inject": inject,
            "offset_ms": token_ms}


@pytest.mark.unit
def test_stale_token_with_rotation_is_classified(tmp_path):
    _session(tmp_path / "s1", {"outcome": "token_stale", "reason": "token_stale: challenge_identity_changed",
                               "task_id": "101", "polls": 3, "attempts": 2, "method": "auto",
                               "url": "https://arena.ai/image/direct"}, [_state()])
    out = analyze(tmp_path / "s1")
    assert "STALE-TOKEN (challenge/sitekey rotated)" in out
    assert "code=hardened" in out


@pytest.mark.unit
def test_not_accepted_without_post_token_request_hints_wrong_callback(tmp_path):
    events = [_state(token_ms=40000, dialog="visible")]
    # only grecaptcha traffic — no post-token request to the page host
    events.append({"seq": 2, "kind": "network_request", "offset_ms": 41500,
                   "url": "https://www.google.com/recaptcha/api2/anchor", "method": "GET"})
    _session(tmp_path / "s2", {"outcome": "auto_failed",
                               "reason": "not_accepted: dialog still visible after token injection",
                               "task_id": "102", "polls": 1, "attempts": 2, "method": "auto",
                               "url": "https://arena.ai/image/direct"}, events)
    out = analyze(tmp_path / "s2")
    assert "NOT-ACCEPTED" in out and "WRONG-CALLBACK suspicion" in out


@pytest.mark.unit
def test_not_accepted_with_post_token_request_has_no_hint(tmp_path):
    events = [_state(token_ms=40000, dialog="visible"),
              {"seq": 2, "kind": "network_request", "offset_ms": 42000,
               "url": "https://arena.ai/api/verify", "method": "POST"}]
    _session(tmp_path / "s3", {"outcome": "auto_failed",
                               "reason": "not_accepted: dialog still visible after token injection",
                               "task_id": "103", "polls": 1, "attempts": 1, "method": "auto",
                               "url": "https://arena.ai/image/direct"}, events)
    out = analyze(tmp_path / "s3")
    assert "NOT-ACCEPTED" in out and "WRONG-CALLBACK" not in out


@pytest.mark.unit
def test_pre_hardening_manifest_is_flagged(tmp_path):
    _session(tmp_path / "s4", {"outcome": "token_stale", "reason": "token_stale: page_identity_changed",
                               "method": "auto", "url": "https://arena.ai/image/direct"}, [_state()])
    out = analyze(tmp_path / "s4")
    assert "PRE-HARDENING" in out
    assert "STALE-TOKEN (challenge/sitekey rotated)" in out


@pytest.mark.unit
def test_solved_and_dialog_gone_classified(tmp_path):
    _session(tmp_path / "s5", {"outcome": "solved", "reason": "token accepted",
                               "task_id": "104", "polls": 2, "attempts": 1, "method": "auto",
                               "url": "https://arena.ai/image/direct"}, [_state()])
    _session(tmp_path / "s6", {"outcome": "auto_failed",
                               "reason": "dialog_gone_during_poll: no solution token",
                               "task_id": "105", "polls": 3, "attempts": 1, "method": "auto",
                               "url": "https://arena.ai/image/direct"}, [])
    assert "SOLVED — bot token accepted" in analyze(tmp_path / "s5")
    assert "DIALOG-GONE" in analyze(tmp_path / "s6")


@pytest.mark.unit
def test_find_session_folders_covers_flat_and_day_layouts(tmp_path):
    _session(tmp_path / "20260101T000000-legacy", {"outcome": "manual", "method": "manual",
                                                   "url": "https://arena.ai/c/1"})
    _session(tmp_path / "2026-09-18" / "20260918T183921-77c22999",
             {"outcome": "page_error", "method": "auto", "url": "https://arena.ai/c/2"})
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    found = _find_session_folders(tmp_path)
    assert [p.name for p in found] == ["20260101T000000-legacy", "20260918T183921-77c22999"]


@pytest.mark.unit
def test_find_session_folders_single_folder_mode(tmp_path):
    _session(tmp_path / "solo", {"outcome": "manual", "method": "manual",
                                 "url": "https://arena.ai/c/3"})
    found = _find_session_folders(tmp_path)
    assert found == [tmp_path / "solo"]


@pytest.mark.unit
def test_legacy_redacted_fields_do_not_crash(tmp_path):
    """Old sanitizer wrote token_at_ms/dialog_at_token as '[REDACTED]' (S-1)."""
    _session(tmp_path / "s7", {"outcome": "page_error", "reason": "page_error: no solution token",
                               "task_id": "", "polls": 13, "attempts": 1, "method": "auto",
                               "url": "https://arena.ai/c/abc"},
             [_state(token_ms="[REDACTED]", dialog="[REDACTED]", inject="")])
    out = analyze(tmp_path / "s7")
    assert "token@0ms" in out
    assert "redacted by old sanitizer" in out
    assert "DEAD-GEN" in out


@pytest.mark.unit
def test_classify_uses_largest_token_state(tmp_path):
    manifest = {"outcome": "token_stale", "reason": "token_stale: challenge_identity_changed"}
    assert "dialog already gone at token" in _classify(
        manifest, [_state(dialog="visible"), _state(dialog="gone")])
