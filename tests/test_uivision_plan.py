"""The multi-profile planner — sessions × pattern → one macro run per matching tab.

RULE 8: pure functions over fake session rows; every rule below would break the
user's fix if deleted (both profiles seen, every matching tab planned, each run
addressing its own profile instance and its own savelog).
"""

from pathlib import Path

import pytest

from app.browser.uivision import launch, paths, plan

pytestmark = pytest.mark.unit

WINDOWS_A = [{"index": 1, "active": {"url": "https://arena.ai/a", "title": "A1"},
              "tabs": [{"url": "https://arena.ai/a", "title": "A1"},
                       {"url": "https://other.example", "title": "O"}]}]
WINDOWS_B = [{"index": 1, "active": {"url": "https://arena.ai/b", "title": "B1"},
              "tabs": [{"url": "https://arena.ai/b", "title": "B1"}]}]

SESSIONS = [
    {"name": "Work", "dir": "/ff/p1.work", "rows": WINDOWS_A[0]["tabs"],
     "windows": WINDOWS_A, "source": "recovery.jsonlz4", "stamp": 2.0},
    {"name": "", "dir": "/ff/p2.play", "rows": WINDOWS_B[0]["tabs"],
     "windows": WINDOWS_B, "source": "recovery.jsonlz4", "stamp": 9.0},
]

P_URL = plan.Patterns("", "arena.ai")   # the URL-only search used below


def test_plan_targets_finds_every_match_in_every_profile():
    targets = plan.plan_targets(SESSIONS, P_URL)
    assert [(t.profile_name, t.url) for t in targets] == [
        ("Work", "https://arena.ai/a"), ("", "https://arena.ai/b")]
    assert targets[0].windows == tuple(WINDOWS_A)          # its own profile's windows ride along


def test_plan_targets_title_and_url_filters_combine():
    """Both patterns set: a tab must satisfy BOTH (AND), case-insensitively."""
    targets = plan.plan_targets(SESSIONS, plan.Patterns("A1", "arena.ai/A"))
    assert [t.url for t in targets] == ["https://arena.ai/a"]        # both filters pass
    assert plan.plan_targets(SESSIONS, plan.Patterns("A1", "other.example")) == []  # URL filter fails
    assert plan.plan_targets(SESSIONS, plan.Patterns("no-such-title", "arena.ai")) == []
    assert plan.plan_targets(SESSIONS, plan.Patterns("b1", ""))[0].profile_name == ""  # title, any case


def test_plan_targets_blank_pattern_means_any():
    """The owner's rule: blank title = any title, blank URL = any URL."""
    assert [t.url for t in plan.plan_targets(SESSIONS, P_URL)] == [
        "https://arena.ai/a", "https://arena.ai/b"]                  # URL-only search
    assert [t.title for t in plan.plan_targets(SESSIONS, plan.Patterns("A1", ""))] == ["A1"]
    both_blank = plan.plan_targets(SESSIONS, plan.Patterns())
    assert sorted(t.url for t in both_blank) == ["https://arena.ai/a",
                                                 "https://arena.ai/b",
                                                 "https://other.example"]
    assert plan.plan_targets(SESSIONS, plan.Patterns("  ", "  ")) == both_blank     # whitespace = blank


def test_matches_is_the_one_predicate():
    assert plan.matches("Arena", "https://arena.ai/image/x", plan.Patterns("arena", "image")) is True
    assert plan.matches("Arena", "https://arena.ai/x", plan.Patterns("arena", "image")) is False   # URL fails
    assert plan.matches("Other", "https://arena.ai/x", plan.Patterns("arena", "")) is False        # title fails
    assert plan.matches("Other", "https://x.example", plan.Patterns()) is True               # any tab
    assert plan.matches("", "https://arena.ai/x", plan.Patterns("", "arena")) is True              # URL-only
    assert plan.matches(None, None, plan.Patterns("a", "b")) is False                              # junk rows


def test_describe_search_names_the_active_filters():
    assert plan.describe_search(plan.Patterns("arena", "image")) == 'title “arena” + URL “image”'
    assert plan.describe_search(plan.Patterns("", "image")) == 'any title + URL “image”'
    assert plan.describe_search(plan.Patterns("arena", "")) == 'title “arena” + any URL'
    assert plan.describe_search(plan.Patterns("  ", "  ")) == plan.ANY_TAB


def test_split_unaddressable_separates_titleless_matches():
    """A URL match without a title has no title glob — it cannot be selected."""
    sessions = [{"name": "Work", "dir": "/ff/p1", "windows": [], "rows": [
        {"url": "https://arena.ai/titled", "title": "Titled"},
        {"url": "https://arena.ai/blank", "title": ""}]}]
    targets = plan.plan_targets(sessions, P_URL)
    ok, skipped = plan.split_unaddressable(targets, plan.Patterns())
    assert [t.url for t in ok] == ["https://arena.ai/titled"]
    assert [t.url for t in skipped] == ["https://arena.ai/blank"]
    with_title_pattern, none = plan.split_unaddressable(targets, plan.Patterns("Titled"))
    assert len(with_title_pattern) == 2 and none == []     # the pattern glob is the fallback


def test_plan_targets_order_is_stable_and_empty_sessions_match_none():
    two = plan.plan_targets(SESSIONS, P_URL)
    again = plan.plan_targets(SESSIONS, P_URL)
    assert two == again
    assert plan.plan_targets([], plan.Patterns("arena")) == []           # no sessions → no targets
    assert plan.plan_targets(None, plan.Patterns("arena")) == []


def test_selector_prefers_the_user_pattern_over_tab_title():
    """The per-tab selector: user's pattern is preferred, tab title is fallback.

    When the user sets a pattern (e.g., "arena"), it's used as the selector —
    shorter, more robust, and reflects the user's intent. Only when the pattern
    is empty does the tab's full title become the selector (2026-09-24 fix for
    E212 errors when the session store title is stale).
    """
    target = plan.Target(profile_name="Work", url="https://arena.ai/b", title="Arena — chat")
    fallback = plan.Target()
    # user pattern set → use it (even when the tab has its own title)
    assert plan.selector_for(target, plan.Patterns("arena")) == "title=*arena*"
    assert plan.selector_for(fallback, plan.Patterns("arena")) == "title=*arena*"
    # user pattern empty → fall back to the tab's title
    assert plan.selector_for(target, plan.Patterns()) == "title=*Arena — chat*"
    assert plan.selector_for(target, plan.Patterns("  ")) == "title=*Arena — chat*"
    # both empty → no selector
    assert plan.selector_for(fallback, plan.Patterns()) == ""
    assert plan.selector_for(fallback, plan.Patterns("  ")) == ""


def test_selector_truncates_long_tab_titles():
    """Long titles from the session store are fragile — truncate to survive changes."""
    long_title = "Directly Chat with Frontier Image Generation AI Models — Arena"
    target = plan.Target(title=long_title)
    selector = plan.selector_for(target, plan.Patterns())
    assert len(selector) <= plan.TITLE_SELECTOR_MAX + len("title=**")
    assert selector.startswith("title=*")
    assert selector.endswith("*")
    # the clipped title is the first TITLE_SELECTOR_MAX chars
    inner = selector[len("title=*"):-1]
    assert inner == long_title[:plan.TITLE_SELECTOR_MAX]


def test_profile_label_prefers_the_ini_name_then_the_basename():
    assert plan.profile_label("Work", "/ff/p1") == "Work"
    assert plan.profile_label("", "/ff/p2.play") == "p2.play"
    assert plan.profile_label("", "") == ""
    assert plan.profile_label("  ", "") == ""


def test_anonymous_session_wraps_the_flat_rows_seam():
    session = plan.anonymous_session([{"url": "https://x", "title": "X"}])
    assert session["name"] == "" and session["windows"] == []
    assert plan.plan_targets([session], plan.Patterns("x"))[0].url == "https://x"
    assert plan.anonymous_session(None)["rows"] == []


def test_runs_render_selector_profile_args_and_per_run_savelogs(tmp_path):
    """Each planned run: own title selector, own -P prefix, own savelog file."""
    targets = plan.plan_targets(SESSIONS, P_URL)
    runs = plan.runs(targets, plan.Patterns(), tmp_path, "20260923-120000")
    assert [r.index for r in runs] == [1, 2] and runs[0].total == 2
    assert runs[0].selector == "title=*A1*" and runs[1].selector == "title=*B1*"
    assert runs[0].profile_args == ("-P", "Work")          # named → -P name
    assert runs[1].profile_args == ("-profile", "/ff/p2.play")   # unnamed → -profile dir
    assert Path(runs[0].log_path).name == "run-20260923-120000.txt"   # run 1 keeps the plain name
    assert Path(runs[1].log_path).name == "run-20260923-120000-2.txt"  # run 2 never overwrites it
    assert runs[1].label == "profile “p2.play” · tab “B1”"


def test_runs_fallback_target_uses_the_plain_handoff(tmp_path):
    """No store answer / no match: today's single run — no -P, the pattern glob."""
    runs = plan.runs([plan.Target()], plan.Patterns("arena.ai"), tmp_path, "S")
    assert len(runs) == 1
    assert runs[0].profile_args == () and runs[0].selector == "title=*arena.ai*"


def test_one_per_profile_keeps_the_first_match_of_each_profile():
    """The 2026-09-24 first-run rule: a profile with N matches runs EXACTLY once."""
    same = [{"url": "https://arena.ai/1", "title": "Same"},
            {"url": "https://arena.ai/2", "title": "Same"}]
    dup = [{"name": "Work", "dir": "/ff/p1", "rows": same, "windows": [
        {"index": 1, "active": {}, "tabs": same}], "source": "", "stamp": 0.0}]
    targets = plan.plan_targets(dup, P_URL)
    assert len(targets) == 2                                # both MATCH …
    assert plan.one_per_profile(targets) == [targets[0]]    # … but one run, first tab
    # one match per profile → nothing collapses, order kept
    assert plan.one_per_profile(plan.plan_targets(SESSIONS, P_URL)) == \
        plan.plan_targets(SESSIONS, P_URL)
    # the flat tabs seam is one anonymous profile → a single run
    flat = plan.plan_targets([plan.anonymous_session(same)], P_URL)
    assert len(plan.one_per_profile(flat)) == 1
    assert plan.one_per_profile([]) == [] and plan.one_per_profile(None) == []


def test_summarize_counts_runs_per_profile():
    targets = plan.plan_targets(SESSIONS, P_URL)
    assert plan.summarize(targets, True) == '2 macro run(s) — “Work” ×1, “p2.play” ×1'
    assert plan.summarize(targets, False) == ("2 macro run(s) — one Firefox instance "
                                              "(no profile selection)")


def test_launch_profile_args_and_argv():
    assert launch.profile_args("Work") == ("-P", "Work")
    assert launch.profile_args("", "/ff/p2") == ("-profile", "/ff/p2")
    assert launch.profile_args("", "") == ()
    argv = launch.profile_argv("/usr/bin/firefox", "file:///x?macro=M", ("-P", "Work"))
    assert argv == ["/usr/bin/firefox", "-P", "Work", "-new-tab", "file:///x?macro=M"]
    assert launch.profile_argv("/usr/bin/firefox", "file:///x") == \
        launch.build_argv("/usr/bin/firefox", "file:///x")     # no profile → the plain argv
    with pytest.raises(ValueError, match="debugger/driver"):
        launch.profile_argv("/usr/bin/firefox", "file:///x", ("-P", "no-remote"))


def test_paths_log_file_parts_never_share_a_file(tmp_path):
    first = paths.log_file(tmp_path, "S")
    second = paths.log_file(tmp_path, "S", part=2)
    assert first.name == "run-S.txt" and second.name == "run-S-2.txt"
    assert first != second
