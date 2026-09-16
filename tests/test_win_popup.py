"""Tests for app/utils/win_popup.py — popup-on-top window matching.

Pure matching is fully tested; the ctypes enumeration only runs on
Windows (guarded no-op elsewhere, covered by the platform test).
"""

import sys

import pytest

from app.utils import win_popup as wp


@pytest.mark.unit
def test_normalize_title():
    assert wp.normalize_title("(3) Directly Chat - Google Chrome") == "(3) directly chat"
    assert wp.normalize_title("  ARENA  ") == "arena"
    assert wp.normalize_title("") == ""
    assert wp.normalize_title(None) == ""
    assert wp.normalize_title(42) == ""


@pytest.mark.unit
def test_pick_windows_exact_and_contains():
    wins = [(11, "(3) Directly Chat - Google Chrome"),
            (22, "Inbox - Mozilla Thunderbird"),
            (33, "Untitled - Notepad")]
    assert wp.pick_windows(wins, ["(3) Directly Chat"]) == [11]
    assert wp.pick_windows(wins, ["directly chat - google chrome"]) == [11]
    assert wp.pick_windows(wins, ["notepad"]) == [33]
    assert wp.pick_windows(wins, ["missing"]) == []
    assert wp.pick_windows(wins, []) == []
    assert wp.pick_windows([], ["x"]) == []


@pytest.mark.unit
def test_pick_windows_skips_junk_and_dedups():
    wins = [(11, "Arena - Google Chrome"), ("bad", "Arena - Google Chrome"),
            (22, ""), (33, None)]
    assert wp.pick_windows(wins, ["arena"]) == [11]


@pytest.mark.unit
def test_raise_noop_off_windows_or_empty(monkeypatch):
    assert wp.raise_window_titles([]) == 0
    assert wp.raise_window_titles([""]) == 0
    monkeypatch.setattr(sys, "platform", "linux")
    assert wp.raise_window_titles(["arena"]) == 0
