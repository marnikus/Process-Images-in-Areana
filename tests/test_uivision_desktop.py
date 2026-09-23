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
