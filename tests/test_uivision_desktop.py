"""Firefox window discovery + foreground — the visible-and-front critical rule.

`desktop` composes the two utils leaves (win_find finds, win_popup raises);
the seams are monkeypatched so the composition rules are testable off-Windows.
"""

import pytest

from app.browser.uivision import desktop
from app.utils import win_find, win_popup

pytestmark = pytest.mark.unit

WINDOWS = [(11, "Arena — Mozilla Firefox", 101),
           (22, "Arena Chat — Mozilla Firefox", 102),
           (33, "Notes — Notepad", 103)]


@pytest.fixture
def fake_desktop(monkeypatch):
    procs = {101: "firefox.exe", 102: "firefox.exe", 103: "notepad.exe"}
    raised = []
    monkeypatch.setattr(win_find, "visible_windows", lambda: WINDOWS)
    monkeypatch.setattr(win_find, "process_name", lambda pid: procs.get(pid, ""))
    monkeypatch.setattr(win_popup, "raise_handles",
                        lambda handles: raised.append(list(handles)) or len(handles))
    return raised


def test_find_windows_filters_by_process_and_pattern(fake_desktop):
    assert desktop.find_windows("Arena") == [(11, "Arena — Mozilla Firefox"),
                                             (22, "Arena Chat — Mozilla Firefox")]
    assert desktop.find_windows("arena chat") == [(22, "Arena Chat — Mozilla Firefox")]
    assert desktop.find_windows("Notepad") == []        # right title, wrong process


def test_empty_pattern_claims_no_window(fake_desktop):
    assert desktop.find_windows("") == []
    assert desktop.find_windows("   ") == []


def test_foreground_raises_every_match(fake_desktop):
    matches, raised = desktop.foreground("Arena")
    assert [hwnd for hwnd, _title in matches] == [11, 22]
    assert raised == 2
    assert fake_desktop == [[11, 22]]


def test_off_windows_the_finder_answers_zero_windows():
    matches, raised = desktop.foreground("Arena")       # real leaf: [] on non-win32
    assert (matches, raised) == ([], 0)


def test_normalize_window_title_strips_firefoxs_own_suffix():
    assert desktop.normalize_window_title("Arena — Mozilla Firefox") == "arena"
    assert desktop.normalize_window_title("Arena - Mozilla Firefox") == "arena"
    assert desktop.normalize_window_title("Arena") == "arena"
    assert desktop.normalize_window_title("") == ""


WINDOWS_SESSION = [
    {"index": 1, "active": {"url": "https://arena.ai/x", "title": "Arena"},
     "tabs": [{"url": "https://arena.ai/x", "title": "Arena"},
              {"url": "https://example.com", "title": "Ex"}]},
    {"index": 2, "active": {"url": "https://chat.example", "title": "Arena Chat"},
     "tabs": [{"url": "https://chat.example", "title": "Arena Chat"}]},
]


def test_pick_tab_window_maps_the_os_window_to_the_tab_holder():
    os_windows = [(11, "Arena — Mozilla Firefox"), (22, "Arena Chat — Mozilla Firefox")]
    assert desktop.pick_tab_window(os_windows, WINDOWS_SESSION, "arena.ai") == [
        (11, "Arena — Mozilla Firefox")]
    assert desktop.pick_tab_window(os_windows, WINDOWS_SESSION, "chat.example") == [
        (22, "Arena Chat — Mozilla Firefox")]
    assert desktop.pick_tab_window(os_windows, WINDOWS_SESSION, "zzz-no-match") == []
    assert desktop.pick_tab_window(os_windows, WINDOWS_SESSION, "") == []
    assert desktop.pick_tab_window(os_windows, [], "arena.ai") == []


def test_pick_tab_window_falls_back_to_contains_only_without_exact():
    session = [{"index": 1, "active": {"url": "https://arena.ai/x", "title": "Arena Portal"},
                "tabs": [{"url": "https://arena.ai/x", "title": "Arena Portal"}]}]
    os_windows = [(11, "Arena — Mozilla Firefox")]
    assert desktop.pick_tab_window(os_windows, session, "arena.ai") == os_windows


def test_foreground_tab_window_raises_only_the_holder(fake_desktop):
    mapped = desktop.foreground_tab_window("arena.ai", WINDOWS_SESSION)
    assert mapped == ([(11, "Arena — Mozilla Firefox")], 1)
    assert fake_desktop == [[11]]                       # the other Arena window stays down


def test_foreground_tab_window_refuses_an_ambiguous_title(monkeypatch):
    """2026-09-25: two OS windows share the tab title → raise NOTHING, report (hits, 0).

    The log of the first-run report showed `2/2` raises for a single-target run —
    two profiles on the same page have the same title and no profile attribution,
    so a guess could put the WRONG instance on top of the native click.
    """
    twin = [(11, "Arena Chat — Mozilla Firefox", 101),
            (22, "Arena Chat — Mozilla Firefox", 102)]   # visible_windows rows: hwnd, title, pid
    raised = []
    monkeypatch.setattr(win_find, "visible_windows", lambda: twin)
    monkeypatch.setattr(win_find, "process_name", lambda pid: "firefox.exe")
    monkeypatch.setattr(win_popup, "raise_handles",
                        lambda handles: raised.append(list(handles)) or len(handles))
    session = [{"index": 1, "active": {"url": "https://arena.ai/x", "title": "Arena Chat"},
                "tabs": [{"url": "https://arena.ai/x", "title": "Arena Chat"}]}]
    hits = [(hwnd, title) for hwnd, title, _pid in twin]
    assert desktop.foreground_tab_window("Arena", session) == (hits, 0)
    assert raised == []                       # the macro's bring decides at click time


def test_foreground_tab_window_answers_none_when_unmapped(fake_desktop):
    assert desktop.foreground_tab_window("zzz-no-match", WINDOWS_SESSION) is None
    assert desktop.foreground_tab_window("arena.ai", []) is None
    assert fake_desktop == []
