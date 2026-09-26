"""I-64 · The Ui.Vision address of a Firefox tab: "title + relative index" (pure).

`selectWindow title=G` takes the FIRST tab whose title matches the glob G, and
`tab=K` steps K tabs right of the re-anchored active tab. So a target is reached
through the nearest tab at or left of it (same window) that is its own title's
first match. Everything else is a named refusal.
"""

import pytest

from app.browser.uivision.pool.locator import (TITLE_MAX, Address, first_match, glob_regex, locate,
                                               refusal, title_glob)

pytestmark = pytest.mark.unit


def w(*titles):
    return [{"url": f"https://arena.ai/{i}", "title": t} for i, t in enumerate(titles)]


def test_a_uniquely_titled_target_needs_no_offset():
    assert locate([w("New Tab", "Chat A", "Chat B")], 1, 2) == Address("Chat B", 0, 2)


def test_a_shared_title_walks_left_to_its_first_match():
    assert locate([w("LMArena", "LMArena", "LMArena")], 1, 2) == Address("LMArena", 2, 0)


def test_the_nearest_self_first_anchor_wins():
    assert locate([w("LMArena", "Google", "LMArena", "LMArena")], 1, 3) == Address("Google", 2, 1)


def test_blank_titles_are_never_anchors():
    assert locate([w("Docs", "", "LMArena")], 1, 1) == Address("Docs", 1, 0)


def test_a_second_window_needs_its_own_first_match():
    shared = [w("LMArena"), w("LMArena", "LMArena")]
    assert locate(shared, 2, 1) is None
    assert "FIRST match" in refusal(shared, 2, 1)
    assert locate([w("LMArena"), w("Docs", "LMArena")], 2, 1) == Address("Docs", 1, 0)


def test_matching_is_case_insensitive_so_firefox_never_picks_an_earlier_tab():
    # `title=LMArena` could hit the earlier "lmarena" under a case-insensitive match, so the
    # target is reached from that tab instead — the same tab under either case rule
    assert locate([w("lmarena", "LMArena")], 1, 1) == Address("lmarena", 1, 0)
    # conservative: an earlier case-variant in another window blocks the anchor (refused by name)
    assert locate([w("lmarena"), w("LMArena")], 2, 0) is None


def test_titles_the_extension_would_rewrite_become_one_char_wildcards():
    assert title_glob(' a"b$c\\ ') == '?a?b?c??'
    assert title_glob("  ") == "" and title_glob(None) == ""
    assert title_glob("x" * 200) == "x" * TITLE_MAX + "*"
    assert glob_regex('?a?b?c??').fullmatch(' a"b$c\\ ')
    assert glob_regex("Chat*").fullmatch("chat 42") and not glob_regex("Chat").fullmatch("Chat 42")


def test_wildcards_inside_a_title_are_emulated_like_firefox():
    windows = [w("A*", "Abc")]
    assert first_match(windows, "A*") == (1, 0)              # "A*" also matches "Abc" — tab 0 comes first
    assert locate(windows, 1, 1) == Address("Abc", 0, 1)     # "Abc" matches only itself
    assert first_match(windows, "B") is None


def test_a_gone_position_is_refused_by_name():
    assert locate([w("A")], 1, 5) is None and locate([w("A")], 3, 0) is None
    assert "no longer at its recorded place" in refusal([w("A")], 1, 5)
