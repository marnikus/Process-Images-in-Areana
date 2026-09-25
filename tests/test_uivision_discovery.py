"""`uivision/discovery` — stable tab ids, session scans, honest misses (design D-2).

Real discovery reads profile session stores that differ per machine, so every
test injects the module's own `sessions` / `in_use` seams — no Firefox needed.
"""

from pathlib import Path

import pytest

from app.browser.uivision import discovery
from app.core.browser_ids import is_tab_id

pytestmark = pytest.mark.unit


def session(dir_, rows, name="Profile1"):
    return {"name": name, "dir": dir_, "rows": rows, "windows": (("win-1",),)}


TWO_PROFILES = [
    session("/profiles/9THrgpBc.Profile1", [
        {"url": "https://arena.ai/c/1", "title": "Arena"},
        {"url": "https://chatgpt.com/", "title": "ChatGPT"},
    ]),
    session("/profiles/7KxQzz.Pro", [
        {"url": "https://arena.ai/c/2", "title": "Arena 2"},
    ], name=""),
]


def test_tab_id_is_the_profile_basename_plus_the_session_index():
    assert discovery.tab_id_for("/profiles/9THrgpBc.Profile1", 6) == "9THrgpBc.Profile1_tab6"
    assert discovery.tab_id_for("/profiles/7KxQzz.Pro", 0) == "7KxQzz.Pro_tab0"
    assert discovery.tab_index_of("9THrgpBc.Profile1_tab6") == 6
    assert discovery.tab_index_of("a_b_tab12") == 12      # greedy profile part
    assert discovery.tab_index_of("not-ours") == -1


def test_the_stable_id_is_recognised_and_cdp_hex_never_is():
    assert is_tab_id("9THrgpBc.Profile1_tab6")
    assert not is_tab_id("1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d")  # CDP target id
    assert not is_tab_id("Profile1_tab")      # no index
    assert not is_tab_id("Profile1_tabx")     # not a number
    assert not is_tab_id("")
    assert discovery.is_tab_id is is_tab_id    # the seam is re-exported (D-2)


def test_discover_lists_running_profiles_in_a_stable_order():
    first = discovery.discover(sessions=TWO_PROFILES, in_use=lambda d: True)
    second = discovery.discover(sessions=TWO_PROFILES, in_use=lambda d: True)
    assert [t.id for t in first] == ["9THrgpBc.Profile1_tab0", "9THrgpBc.Profile1_tab1",
                                     "7KxQzz.Pro_tab0"]
    assert [t.id for t in second] == [t.id for t in first]
    assert first[1].url == "https://chatgpt.com/"
    assert first[1].profile_dir == "/profiles/9THrgpBc.Profile1"
    assert first[1].browser == "firefox"
    assert first[1].ws_url == ""            # this lane never has a socket


def test_discover_skips_closed_profiles_and_honours_the_selection():
    running = lambda d: d.endswith("Profile1")
    assert [t.id for t in discovery.discover(sessions=TWO_PROFILES, in_use=running)] == [
        "9THrgpBc.Profile1_tab0", "9THrgpBc.Profile1_tab1"]
    wanted = discovery.discover(selected=("/profiles/7KxQzz.Pro",),
                                sessions=TWO_PROFILES, in_use=lambda d: True)
    assert [t.id for t in wanted] == ["7KxQzz.Pro_tab0"]


def test_find_target_resolves_by_id_and_answers_none_when_the_tab_is_gone():
    tab = discovery.find_target("9THrgpBc.Profile1_tab1", sessions=TWO_PROFILES,
                                in_use=lambda d: True)
    assert tab is not None and tab.title == "ChatGPT"
    assert discovery.find_target("9THrgpBc.Profile1_tab9", sessions=TWO_PROFILES,
                                 in_use=lambda d: True) is None
    closed = discovery.find_target("9THrgpBc.Profile1_tab0",
                                   sessions=TWO_PROFILES, in_use=lambda d: False)
    assert closed is None, "a closed profile must never resolve to a stranger tab"


def test_a_session_without_a_dir_or_rows_contributes_nothing():
    assert discovery.discover(sessions=[{"rows": [{"url": "x"}]}], in_use=lambda d: True) == []
    assert discovery.discover(sessions=[session("/p/X", [])], in_use=lambda d: True) == []


def test_the_generated_id_matches_the_owner_format_example():
    example = discovery.tab_id_for(str(Path("/x/9THrgpBc.Profile1")), 6)
    assert example == "9THrgpBc.Profile1_tab6"      # {profileDirName}_{tabIndex}
