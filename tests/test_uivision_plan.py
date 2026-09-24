"""The multi-profile planner — sessions × pattern → one macro run per profile.

RULE 8: pure functions over fake session rows; every rule below would break the
user's fix if deleted (both profiles seen, every profile running exactly once,
title literals used verbatim, URL-driven runs resolved to a fresh tab=N at
launch — never a title glob built from the store).
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


def test_plan_targets_finds_every_match_in_every_profile():
    targets = plan.plan_targets(SESSIONS, "", "arena.ai")
    assert [(t.profile_name, t.url) for t in targets] == [
        ("Work", "https://arena.ai/a"), ("", "https://arena.ai/b")]
    assert targets[0].windows == tuple(WINDOWS_A)          # its own profile's windows ride along


def test_plan_targets_records_window_positions():
    targets = plan.plan_targets(SESSIONS, "", "arena.ai")
    assert [(t.window_index, t.tab_pos) for t in targets] == [(0, 0), (0, 0)]
    second = plan.plan_targets(SESSIONS, "O", "")[0]
    assert (second.window_index, second.tab_pos) == (0, 1)  # second tab of window 0


def test_plan_targets_title_and_url_filters_combine():
    """Both patterns set: a tab must satisfy BOTH (AND), case-insensitively."""
    targets = plan.plan_targets(SESSIONS, "A1", "arena.ai/A")
    assert [t.url for t in targets] == ["https://arena.ai/a"]        # both filters pass
    assert plan.plan_targets(SESSIONS, "A1", "other.example") == []  # URL filter fails
    assert plan.plan_targets(SESSIONS, "no-such-title", "arena.ai") == []
    assert plan.plan_targets(SESSIONS, "b1", "")[0].profile_name == ""  # title, any case


def test_plan_targets_blank_pattern_means_any():
    """The owner's rule: blank title = any title, blank URL = any URL."""
    assert [t.url for t in plan.plan_targets(SESSIONS, "", "arena.ai")] == [
        "https://arena.ai/a", "https://arena.ai/b"]                  # URL-only search
    assert [t.title for t in plan.plan_targets(SESSIONS, "A1", "")] == ["A1"]
    both_blank = plan.plan_targets(SESSIONS, "", "")
    assert sorted(t.url for t in both_blank) == ["https://arena.ai/a",
                                                 "https://arena.ai/b",
                                                 "https://other.example"]
    assert plan.plan_targets(SESSIONS, "  ", "  ") == both_blank     # whitespace = blank


def test_plan_targets_titleless_url_matches_are_planned():
    """A URL match without a title still runs — the tab=N index needs no title."""
    sessions = [{"name": "Work", "dir": "/ff/p1",
                 "windows": [{"index": 1, "active": {"url": "https://arena.ai/blank", "title": ""},
                              "tabs": [{"url": "https://arena.ai/blank", "title": ""}]}],
                 "rows": [], "source": "", "stamp": 1.0}]
    targets = plan.plan_targets(sessions, "", "arena.ai")
    assert [t.url for t in targets] == ["https://arena.ai/blank"]
    assert targets[0].tab_pos == 0


def test_matches_is_the_one_predicate():
    assert plan.matches("Arena", "https://arena.ai/image/x", "arena", "image") is True
    assert plan.matches("Arena", "https://arena.ai/x", "arena", "image") is False   # URL fails
    assert plan.matches("Other", "https://arena.ai/x", "arena", "") is False        # title fails
    assert plan.matches("Other", "https://x.example", "", "") is True               # any tab
    assert plan.matches("", "https://arena.ai/x", "", "arena") is True              # URL-only
    assert plan.matches(None, None, "a", "b") is False                              # junk rows


def test_describe_search_names_the_active_filters():
    assert plan.describe_search("arena", "image") == 'title “arena” + URL “image”'
    assert plan.describe_search("", "image") == 'any title + URL “image”'
    assert plan.describe_search("arena", "") == 'title “arena” + any URL'
    assert plan.describe_search("", "  ") == plan.ANY_TAB


def test_selector_uses_the_user_pattern_verbatim_or_defers():
    """A set title pattern rides verbatim; a blank one defers to launch resolve.

    Nothing is ever built from detection output — the old title-glob fallback
    (session-store titles, truncated) was the E212 source on dynamic pages.
    """
    assert plan.selector_for("arena") == "title=*arena*"
    assert plan.selector_for("  Agent Arena  ") == "title=*Agent Arena*"
    assert plan.selector_for("") == ""    # launch resolves a fresh tab=N instead
    assert plan.selector_for("  ") == ""


def test_profile_label_prefers_the_ini_name_then_the_basename():
    assert plan.profile_label("Work", "/ff/p1") == "Work"
    assert plan.profile_label("", "/ff/p2.play") == "p2.play"
    assert plan.profile_label("", "") == ""
    assert plan.profile_label("  ", "") == ""


def test_anonymous_session_wraps_the_flat_rows_seam():
    session = plan.anonymous_session([{"url": "https://x", "title": "X"}])
    assert session["name"] == "" and session["windows"] == []
    assert plan.plan_targets([session], "x")[0].url == "https://x"
    assert plan.anonymous_session(None)["rows"] == []


def test_runs_by_profile_groups_tabs_into_one_run_per_profile(tmp_path):
    """Two matching tabs in ONE profile → ONE run (the first match addresses it)."""
    one = [{"name": "Work", "dir": "/ff/p1.work", "rows": [],
            "windows": [{"index": 1, "active": {"url": "https://arena.ai/1", "title": "First"},
                         "tabs": [{"url": "https://arena.ai/1", "title": "First"},
                                  {"url": "https://arena.ai/2", "title": "Second"}]}],
            "source": "", "stamp": 1.0}]
    targets = plan.plan_targets(one, "", "arena.ai")
    runs = plan.runs_by_profile(targets, plan.Search(url_pattern="arena.ai"),
                                tmp_path, "20260924-120000")
    assert len(runs) == 1
    assert runs[0].total == 1 and runs[0].target.title == "First"
    assert [t.title for t in runs[0].tabs] == ["First", "Second"]
    assert runs[0].profile_args == ("-P", "Work")
    assert Path(runs[0].log_path).name == "run-20260924-120000.txt"


def test_runs_by_profile_renders_selector_profile_args_and_savelogs(tmp_path):
    """Each profile run: its own -P prefix, its own savelog file, title literal."""
    targets = plan.plan_targets(SESSIONS, "A", "arena.ai")
    search = plan.Search(pattern="A", url_pattern="arena.ai")
    runs = plan.runs_by_profile(targets, search, tmp_path, "20260923-120000")
    assert [r.index for r in runs] == [1] and runs[0].total == 1   # only "A1" passes both
    assert runs[0].selector == "title=*A*"                          # the user's literal
    assert runs[0].profile_args == ("-P", "Work")                   # named → -P name
    assert Path(runs[0].log_path).name == "run-20260923-120000.txt"
    assert runs[0].label == "profile “Work” · tab “A1”"


def test_runs_by_profile_url_search_defers_the_selector_to_launch(tmp_path):
    """URL-only search: the selector is "" — the launch resolves a fresh tab=N."""
    targets = plan.plan_targets(SESSIONS, "", "arena.ai")
    runs = plan.runs_by_profile(targets, plan.Search(url_pattern="arena.ai"),
                                tmp_path, "20260923-120000")
    assert [r.index for r in runs] == [1, 2] and runs[0].total == 2
    assert runs[0].selector == "" and runs[1].selector == ""
    assert runs[0].profile_args == ("-P", "Work")          # named → -P name
    assert runs[1].profile_args == ("-profile", "/ff/p2.play")   # unnamed → -profile dir
    assert Path(runs[0].log_path).name == "run-20260923-120000.txt"   # run 1 keeps the plain name
    assert Path(runs[1].log_path).name == "run-20260923-120000-2.txt"  # run 2 never overwrites it
    assert runs[1].label == "profile “p2.play” · tab “B1”"
    assert runs[0].search == plan.Search(url_pattern="arena.ai")  # the resolver reads it


def test_runs_by_profile_fallback_target_uses_the_plain_handoff(tmp_path):
    """No store answer / no match: today's single run — no -P, the pattern glob."""
    runs = plan.runs_by_profile([plan.Target()], plan.Search(pattern="arena.ai"),
                                tmp_path, "S")
    assert len(runs) == 1
    assert runs[0].profile_args == () and runs[0].selector == "title=*arena.ai*"


def test_multi_matches_names_crowded_profiles():
    same = [{"url": "https://arena.ai/1", "title": "Same"},
            {"url": "https://arena.ai/2", "title": "Same"}]
    dup = [{"name": "Work", "dir": "/ff/p1", "rows": same, "windows": [
        {"index": 1, "active": {}, "tabs": same}], "source": "", "stamp": 0.0}]
    targets = plan.plan_targets(dup, "", "arena.ai")
    assert plan.multi_matches(targets) == [("Work", 2, "Same")]
    assert plan.multi_matches(plan.plan_targets(SESSIONS, "", "arena.ai")) == []


def test_summarize_counts_runs_per_profile():
    targets = plan.plan_targets(SESSIONS, "", "arena.ai")
    assert plan.summarize(targets, True) == '2 macro run(s) — “Work” ×1, “p2.play” ×1'
    assert plan.summarize(targets, False) == ("2 macro run(s) — one Firefox instance "
                                              "(no profile selection)")


def test_summarize_counts_one_run_for_a_crowded_profile():
    same = [{"url": "https://arena.ai/1", "title": "Same"},
            {"url": "https://arena.ai/2", "title": "Same"}]
    dup = [{"name": "Work", "dir": "/ff/p1", "rows": same, "windows": [
        {"index": 1, "active": {}, "tabs": same}], "source": "", "stamp": 0.0}]
    targets = plan.plan_targets(dup, "", "arena.ai")
    assert plan.summarize(targets, True) == '1 macro run(s) — “Work” ×2'


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


# ── launch-time tab=N resolution (2026-09-24: URL-driven, never constructed) ──

THREE_TABS = [{"index": 1, "active": {"url": "https://arena.ai/c", "title": "C"},
               "tabs": [{"url": "https://arena.ai/a", "title": "A"},
                        {"url": "https://arena.ai/b", "title": "B"},
                        {"url": "https://arena.ai/c", "title": "C"}]}]


def _url_run(**over):
    kw = dict(profile_name="Work", profile_dir="/ff/w", url="https://arena.ai/b",
              title="B", windows=tuple(THREE_TABS))
    kw.update(over)
    target = plan.Target(**kw)
    return plan.PlannedRun(target=target, index=1, total=1, label="L", selector="",
                           profile_args=("-P", "Work"), log_path="/tmp/l",
                           search=plan.Search(url_pattern="arena.ai"), tabs=(target,))


def _fresh_session(windows):
    return {"name": "Work", "dir": "/ff/w", "rows": [], "windows": windows,
            "source": "", "stamp": 1.0}


def _url_run_for(url_match: str):
    """A URL run whose pattern matches exactly one of the three tabs."""
    target = plan.Target(profile_name="Work", profile_dir="/ff/w",
                         url=f"https://arena.ai/{url_match}", title=url_match.upper(),
                         windows=tuple(THREE_TABS))
    return plan.PlannedRun(target=target, index=1, total=1, label="L", selector="",
                           profile_args=("-P", "Work"), log_path="/tmp/l",
                           search=plan.Search(url_pattern=f"arena.ai/{url_match}"),
                           tabs=(target,))


def test_resolve_selector_addresses_url_matches_by_relative_index():
    """tab=N counts back from the autostart tab (it appends last, so N is negative)."""
    run = _url_run_for("b")
    selector, windows = plan.resolve_selector(run, [_fresh_session(THREE_TABS)])
    assert selector == "tab=-2"                      # "B" is the middle of three
    assert windows == [THREE_TABS[0]]                # delivery maps into THIS window


def test_resolve_selector_first_and_last_positions():
    selector, _windows = plan.resolve_selector(_url_run_for("a"),
                                               [_fresh_session(THREE_TABS)])
    assert selector == "tab=-3"
    selector, _windows = plan.resolve_selector(_url_run_for("c"),
                                               [_fresh_session(THREE_TABS)])
    assert selector == "tab=-1"


def test_resolve_selector_blank_search_aims_at_the_first_tab():
    run = _url_run()
    run = plan.PlannedRun(target=run.target, index=1, total=1, label="L", selector="",
                          profile_args=(), log_path="/tmp/l", search=plan.Search(),
                          tabs=(run.target,))
    selector, windows = plan.resolve_selector(run, [_fresh_session(THREE_TABS)])
    assert selector == "tab=-3"                       # first of three, no filter
    assert windows == [THREE_TABS[0]]


def test_resolve_selector_returns_none_when_the_tab_is_gone():
    run = _url_run()
    assert plan.resolve_selector(run, [_fresh_session([])]) is None       # no windows
    assert plan.resolve_selector(run, []) is None                          # profile closed
    other = [_fresh_session([{"index": 1, "active": {}, "tabs": [
        {"url": "https://other.example", "title": "O"}]}])]
    assert plan.resolve_selector(run, other) is None                      # URL no longer there


def test_resolve_selector_title_runs_keep_the_literal():
    target = plan.Target(profile_name="W", profile_dir="/ff/w",
                         url="https://arena.ai/a", title="A",
                         windows=tuple(THREE_TABS))
    run = plan.PlannedRun(target=target, index=1, total=1, label="L",
                          selector="title=*Arena*", profile_args=(), log_path="/tmp/l",
                          search=plan.Search(pattern="Arena"), tabs=(target,))
    selector, windows = plan.resolve_selector(run, [])
    assert selector == "title=*Arena*"                # verbatim — no store read needed
    assert windows == [THREE_TABS[0]]                 # the window holding the target URL


def test_plan_window_finds_the_holder_or_falls_back():
    assert plan.plan_window(THREE_TABS, "https://arena.ai/b") == [THREE_TABS[0]]
    assert plan.plan_window(THREE_TABS, "https://gone.example") == THREE_TABS
    assert plan.plan_window([], "https://arena.ai/a") == []
