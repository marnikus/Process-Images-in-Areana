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


def test_foreground_tab_window_answers_none_when_unmapped(fake_desktop):
    assert desktop.foreground_tab_window("zzz-no-match", WINDOWS_SESSION) is None
    assert desktop.foreground_tab_window("arena.ai", []) is None
    assert fake_desktop == []


# ── delivery choice (2026-09-24: no remoting into running instances) ──

from app.browser.uivision import plan as plan_mod


def _run_for(profile_name="", profile_dir="", url="", windows=()):
    target = plan_mod.Target(profile_name=profile_name, profile_dir=profile_dir,
                             url=url, title="T", windows=tuple(windows))
    return plan_mod.PlannedRun(target=target, index=1, total=1, label="L",
                               selector="", profile_args=(), log_path="/tmp/l")


DELIVERY_WINDOW = {"index": 1,
                   "active": {"url": "https://arena.ai/a", "title": "A1"},
                   "tabs": [{"url": "https://arena.ai/a", "title": "A1"}]}


def test_choose_delivery_fallback_runs_cold_without_profile_args():
    run = _run_for()                                     # Target(): no profile at all
    assert desktop.choose_delivery(run, [(11, "X")], 1) == ("cold", "")
    assert desktop.choose_delivery(run, [], 3) == ("cold", "")   # plain CLI misfires never


def test_choose_delivery_mapped_window_gets_addressbar():
    run = _run_for("Work", "/ff/w", "https://arena.ai/a", [DELIVERY_WINDOW])
    kind, hwnd = desktop.choose_delivery(run, [(11, "A1 — Mozilla Firefox")], 1)
    assert (kind, hwnd) == ("addressbar", 11)


def test_choose_delivery_lone_profile_cold_starts_when_nothing_runs():
    run = _run_for("Work", "/ff/w", "https://arena.ai/a", [DELIVERY_WINDOW])
    assert desktop.choose_delivery(run, [], 1) == ("cold", "")   # the ONE case for -P


def test_choose_delivery_names_the_manual_fallbacks():
    run = _run_for("Work", "/ff/w", "https://arena.ai/a", [DELIVERY_WINDOW])
    kind, reason = desktop.choose_delivery(run, [], 2)
    assert kind == "manual" and "2 profiles match" in reason
    kind, reason = desktop.choose_delivery(run, [(99, "Other — Mozilla Firefox")], 1)
    assert kind == "manual" and "Work" in reason and "no open Firefox window" in reason


def test_choose_delivery_honours_the_resolver_window_map():
    """The same URL in two windows: the resolver's map pins the delivery window."""
    twin = {"index": 2, "active": {"url": "https://arena.ai/a", "title": "A1 copy"},
            "tabs": [{"url": "https://arena.ai/a", "title": "A1 copy"}]}
    run = _run_for("Work", "/ff/w", "https://arena.ai/a", [DELIVERY_WINDOW, twin])
    both = [(11, "A1 — Mozilla Firefox"), (22, "A1 copy — Mozilla Firefox")]
    assert desktop.choose_delivery(run, both, 1, [twin]) == ("addressbar", 22)
    assert desktop.choose_delivery(run, both, 1) == ("addressbar", 11)  # whole map: first hit
