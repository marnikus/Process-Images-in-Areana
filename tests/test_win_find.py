"""win_find — the pure matching rules run anywhere; the OS calls answer honestly.

Utils leaf (stdlib ctypes only): on non-Windows the enumeration returns [] and
process names return "" — a caller needing a real window reports that instead
of faking a match (RULE 4). The matchers are injectable, so they are testable
on any OS.
"""

import sys

import pytest

from app.utils import win_find

pytestmark = pytest.mark.unit

ROWS = [(1, "Arena — Mozilla Firefox", "firefox.exe"),
        (2, "arena chat — Mozilla Firefox", "firefox.exe"),
        (3, "Arena — Brave", "brave.exe"),
        (4, "Notes", "notepad.exe")]


def test_title_has_pattern():
    assert win_find.title_has_pattern("Arena — Mozilla Firefox", "arena")
    assert win_find.title_has_pattern("  ARENA chat ", "arena chat")
    assert not win_find.title_has_pattern("Arena", "chat")
    assert not win_find.title_has_pattern("", "arena")       # no title: no claim
    assert not win_find.title_has_pattern("Arena", "")       # no pattern: no claim
    assert not win_find.title_has_pattern("Arena", "   ")
    assert not win_find.title_has_pattern(None, "arena")


def test_process_matches():
    assert win_find.process_matches("firefox.exe", "firefox")
    assert win_find.process_matches("FIREFOX.EXE", "firefox")
    assert not win_find.process_matches("brave.exe", "firefox")
    assert win_find.process_matches("", "")                  # '' wants every process
    assert win_find.process_matches(None, "")


def test_pick_matches_composes_both_rules():
    assert win_find.pick_matches(ROWS, "arena", "firefox") == [
        (1, "Arena — Mozilla Firefox"), (2, "arena chat — Mozilla Firefox")]
    assert win_find.pick_matches(ROWS, "arena", "") == [row[:2] for row in ROWS[:3]]
    assert win_find.pick_matches([], "arena", "firefox") == []
    assert win_find.pick_matches(None, "arena", "firefox") == []


def test_off_windows_the_os_calls_are_honest_no_ops():
    if sys.platform == "win32":
        pytest.skip("Windows-only enumeration")
    assert win_find.visible_windows() == []
    assert win_find.process_name(1234) == ""
    assert win_find.process_name("not-a-pid") == ""
    assert win_find.process_name(0) == ""
