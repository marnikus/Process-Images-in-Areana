"""The protected-tab rule — pre-existing tabs must survive the run.

RULE 8: pure snapshot/diff over fake sessions; a deleted check would let a
vanished user tab pass silently, which is exactly what these tests forbid.
"""

import pytest

from app.browser.uivision import guard

pytestmark = pytest.mark.unit

BEFORE = [
    {"name": "Work", "dir": "/ff/w",
     "rows": [{"url": "https://arena.ai/a", "title": "A1"},
              {"url": "https://arena.ai/b", "title": "B1"}]},
    {"name": "", "dir": "/ff/p",
     "rows": [{"url": "https://arena.ai/c", "title": "C1"}]},
]


def test_snapshot_freezes_every_tab_url_per_profile():
    frozen = guard.snapshot_tabs(BEFORE)
    assert frozen == {"/ff/w": frozenset({"https://arena.ai/a", "https://arena.ai/b"}),
                      "/ff/p": frozenset({"https://arena.ai/c"})}
    assert guard.snapshot_tabs([]) == {}
    assert guard.snapshot_tabs(None) == {}


def test_verify_snapshot_is_silent_when_everything_survived():
    frozen = guard.snapshot_tabs(BEFORE)
    assert guard.verify_snapshot(frozen, BEFORE) == []
    grown = [dict(session, rows=session["rows"] + [{"url": "file:///autorun", "title": "Auto"}])
             for session in BEFORE]
    assert guard.verify_snapshot(frozen, grown) == []     # new autostart tabs are fine


def test_verify_snapshot_warns_per_vanished_pre_existing_tab():
    frozen = guard.snapshot_tabs(BEFORE)
    after = [{"name": "Work", "dir": "/ff/w",
              "rows": [{"url": "https://arena.ai/b", "title": "B1"}]},
             {"name": "", "dir": "/ff/p", "rows": []}]
    lines = guard.verify_snapshot(frozen, after)
    assert len(lines) == 2
    assert "Work" in lines[0] and "https://arena.ai/a" in lines[0]
    assert "never closes tabs" in lines[0] and "closed outside the run" in lines[0]
    assert "p" in lines[1] and "https://arena.ai/c" in lines[1]


def test_verify_snapshot_skips_the_check_when_nothing_is_readable():
    frozen = guard.snapshot_tabs(BEFORE)
    assert guard.verify_snapshot(frozen, []) == []        # Firefox may have closed
    assert guard.verify_snapshot(frozen, None) == []      # silence is not damage


def test_verify_lines_reports_levels_and_unreadable_stores():
    frozen = guard.snapshot_tabs(BEFORE)
    assert guard.verify_lines(frozen, lambda: BEFORE) == []
    after = [{"name": "Work", "dir": "/ff/w", "rows": []},
             {"name": "", "dir": "/ff/p", "rows": []}]
    lines = guard.verify_lines(frozen, lambda: after)
    assert [level for _line, level in lines] == ["warn", "warn"]

    def refuse():
        raise OSError("locked")

    [(line, level)] = guard.verify_lines(frozen, refuse)
    assert level == "info" and "could not be re-read" in line
