"""Profile listing and selection — the filter the runner applies before planning.

Tests the pure functions in `app/browser/uivision/profiles.py`: listing (the
session-store seam), normalising the selected set, filtering targets and naming
the unmatched profiles. No Qt, no bridge, no OS calls beyond the faked seam.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.browser.uivision import profiles
from app.browser.uivision.plan import Target

pytestmark = pytest.mark.unit


def _target(profile_dir: str, title: str = "T", url: str = "https://x") -> Target:
    return Target(profile_name="", profile_dir=profile_dir, url=url, title=title)


def _session(dir_path: str, name: str, rows: list) -> dict:
    return {"name": name, "dir": dir_path, "rows": rows,
            "windows": [], "source": "recovery.jsonlz4", "stamp": 1.0}


# ── list_profiles (open profiles only — bug #4, 2026-09-24) ─────────────────

def test_list_profiles_returns_every_answering_session(monkeypatch):
    sessions = [
        _session("/p/a", "alpha", [{"url": "https://x/1", "title": "T1"},
                                    {"url": "https://x/2", "title": "T2"}]),
        _session("/p/b", "", [{"url": "https://y", "title": "Y"}]),
    ]
    monkeypatch.setattr(profiles.tabs, "profile_sessions", lambda: sessions)
    rows = profiles.list_profiles(in_use=lambda p: True)
    assert len(rows) == 2
    assert rows[0]["id"] == "/p/a" and rows[0]["name"] == "alpha"
    assert rows[0]["tab_count"] == 2 and len(rows[0]["tabs"]) == 2
    assert rows[1]["name"] == "" and rows[1]["tab_count"] == 1


def test_list_profiles_caps_the_tabs_shown(monkeypatch):
    rows = [{"url": f"https://x/{i}", "title": f"T{i}"} for i in range(20)]
    monkeypatch.setattr(profiles.tabs, "profile_sessions",
                        lambda: [_session("/p", "p", rows)])
    out = profiles.list_profiles(in_use=lambda p: True)
    assert out[0]["tab_count"] == 20 and len(out[0]["tabs"]) == profiles.TAB_CAP


def test_list_profiles_empty_when_no_session_answers(monkeypatch):
    monkeypatch.setattr(profiles.tabs, "profile_sessions", lambda: [])
    assert profiles.list_profiles() == []


def test_list_profiles_lists_only_running_profiles(monkeypatch):
    """Closed-on-disk profiles never appear — the lock probe decides."""
    sessions = [_session("/p/open", "running", [{"url": "https://x", "title": "X"}]),
                _session("/p/closed", "old", [{"url": "https://y", "title": "Y"}])]
    monkeypatch.setattr(profiles.tabs, "profile_sessions", lambda: sessions)
    rows = profiles.list_profiles(in_use=lambda p: p == "/p/open")
    assert [r["id"] for r in rows] == ["/p/open"]
    # default probe (no in_use): the fake dirs answer NOT in use → nothing listed
    assert profiles.list_profiles() == []


def test_open_sessions_filters_by_the_lock_probe():
    sessions = [_session("/p/a", "a", []), _session("/p/b", "b", [])]
    assert profiles.open_sessions(sessions, in_use=lambda p: p == "/p/b") == [
        sessions[1]]
    assert profiles.open_sessions(sessions, in_use=lambda p: True) == sessions
    assert profiles.open_sessions(None, in_use=lambda p: True) == []
    assert profiles.open_sessions([], in_use=lambda p: True) == []


# ── selected_set ─────────────────────────────────────────────────────────────

def test_selected_set_blank_means_every_profile():
    assert profiles.selected_set([]) == set()
    assert profiles.selected_set(None) == set()


def test_selected_set_trims_and_deduplicates():
    assert profiles.selected_set(["/a", " /b ", "", "/a"]) == {"/a", "/b"}


# ── filter_targets ───────────────────────────────────────────────────────────

def test_filter_targets_blank_selection_keeps_every_target():
    targets = [_target("/a"), _target("/b")]
    assert profiles.filter_targets(targets, []) == targets


def test_filter_targets_keeps_only_selected_profiles():
    a, b, c = _target("/a"), _target("/b"), _target("/c")
    out = profiles.filter_targets([a, b, c], ["/a", "/c"])
    assert out == [a, c]


def test_filter_targets_empty_input_stays_empty():
    assert profiles.filter_targets([], ["/a"]) == []
    assert profiles.filter_targets(None, ["/a"]) == []


# ── unmatched_profiles ───────────────────────────────────────────────────────

def test_unmatched_profiles_names_selected_profiles_with_no_matching_tab():
    sessions = [_session("/a", "alpha", []), _session("/b", "beta", [])]
    targets = [_target("/a", title="T")]   # alpha has a hit, beta has none
    out = profiles.unmatched_profiles(sessions, targets, ["/a", "/b"])
    assert out == ["beta"]


def test_unmatched_profiles_blank_selection_reports_every_unmatched():
    sessions = [_session("/a", "alpha", []), _session("/b", "beta", [])]
    targets = [_target("/a", title="T")]
    out = profiles.unmatched_profiles(sessions, targets, [])
    assert out == ["beta"]


def test_unmatched_profiles_ignores_deselected_profiles():
    sessions = [_session("/a", "alpha", []), _session("/b", "beta", [])]
    targets = []
    out = profiles.unmatched_profiles(sessions, targets, ["/a"])
    assert out == ["alpha"]   # beta is deselected: not reported
