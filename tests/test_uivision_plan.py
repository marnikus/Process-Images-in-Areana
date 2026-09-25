"""The per-profile planner — sessions × the owner's patterns → one run per profile.

RULE 8: pure functions over fake session rows; every rule below would break the
owner's 2026-09-24 rebuild if deleted (the run unit is the PROFILE, the
locator comes ONLY from the configured patterns — never from a clipped
detected title, every profile is run exactly once).
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


def test_plan_targets_gives_every_open_profile_with_a_match_one_target():
    targets = plan.plan_targets(SESSIONS, plan.Search("", "arena.ai"))
    assert [(t.profile_name, t.url) for t in targets] == [
        ("Work", "https://arena.ai/a"), ("", "https://arena.ai/b")]
    assert targets[0].windows == tuple(WINDOWS_A)          # its own profile's windows ride along


def test_plan_targets_second_tab_of_one_profile_gets_no_second_run():
    """Bug #3: the run unit is the profile — two matching tabs still one run."""
    session = {"name": "Work", "dir": "/ff/p1.work", "windows": WINDOWS_A,
               "rows": [{"url": "https://arena.ai/a", "title": "A1"},
                        {"url": "https://arena.ai/c", "title": "A2"}],
               "source": "recovery.jsonlz4", "stamp": 2.0}
    targets = plan.plan_targets([session], plan.Search("", "arena.ai"))
    assert [t.url for t in targets] == ["https://arena.ai/a"]   # the FIRST titled match
    assert plan.match_counts([session], plan.Search("", "arena.ai")) == [("Work", 2)]


def test_plan_targets_representative_skips_the_titleless_match():
    """A titleless match cannot be the representative (selectWindow needs a title)."""
    session = {"name": "Work", "dir": "/ff/p1", "windows": [],
               "rows": [{"url": "https://arena.ai/blank", "title": ""},
                        {"url": "https://arena.ai/titled", "title": "Titled"}],
               "source": "", "stamp": 0.0}
    targets = plan.plan_targets([session], plan.Search("", "arena.ai"))
    assert [t.url for t in targets] == ["https://arena.ai/titled"]
    assert plan.unmatchable_profiles([session], plan.Search("", "arena.ai")) == []


def test_unmatchable_profiles_names_the_all_titleless_ones():
    all_blank = {"name": "Work", "dir": "/ff/p1", "windows": [],
                 "rows": [{"url": "https://arena.ai/1", "title": ""},
                          {"url": "https://arena.ai/2", "title": ""}],
                 "source": "", "stamp": 0.0}
    mixed = {"name": "Play", "dir": "/ff/p2", "windows": [],
             "rows": [{"url": "https://arena.ai/1", "title": ""},
                      {"url": "https://arena.ai/2", "title": "Ok"}],
             "source": "", "stamp": 0.0}
    assert plan.plan_targets([all_blank], plan.Search("", "arena.ai")) == []
    assert plan.unmatchable_profiles([all_blank], plan.Search("", "arena.ai")) == [("Work", 2)]
    assert plan.unmatchable_profiles([mixed], plan.Search("", "arena.ai")) == []  # one titled


def test_plan_targets_title_and_url_filters_combine():
    """Both patterns set: a tab must satisfy BOTH (AND), case-insensitively."""
    targets = plan.plan_targets(SESSIONS, plan.Search("A1", "arena.ai/A"))
    assert [t.url for t in targets] == ["https://arena.ai/a"]        # both filters pass
    assert plan.plan_targets(SESSIONS, plan.Search("A1", "other.example")) == []  # URL fails
    assert plan.plan_targets(SESSIONS, plan.Search("no-such-title", "arena.ai")) == []
    assert plan.plan_targets(SESSIONS, plan.Search("b1", ""))[0].profile_name == ""  # any case


def test_plan_targets_blank_pattern_means_any():
    """The owner's rule: blank title = any title, blank URL = any URL — one run per profile."""
    assert [t.url for t in plan.plan_targets(SESSIONS, plan.Search("", "arena.ai"))] == [
        "https://arena.ai/a", "https://arena.ai/b"]                  # URL-only search
    assert [t.title for t in plan.plan_targets(SESSIONS, plan.Search("A1", ""))] == ["A1"]
    both_blank = plan.plan_targets(SESSIONS, plan.Search("", ""))
    # every PROFILE runs once; the first titled tab of each is the representative
    assert sorted(t.url for t in both_blank) == ["https://arena.ai/a", "https://arena.ai/b"]
    assert plan.plan_targets(SESSIONS, plan.Search("  ", "  ")) == both_blank  # blank = blank


def test_plan_targets_ignores_a_duplicate_session_of_the_same_profile():
    """The same profile dir twice (two stores agreeing) still plans ONE run."""
    dup = [
        {"name": "Work", "dir": "/ff/a", "rows": [
            {"url": "https://arena.ai/1", "title": "First"}], "windows": [],
         "source": "", "stamp": 1.0},
        {"name": "Work", "dir": "/ff/a", "rows": [
            {"url": "https://arena.ai/2", "title": "Second"}], "windows": [],
         "source": "", "stamp": 2.0},
    ]
    assert [t.url for t in plan.plan_targets(dup, plan.Search("", "arena.ai"))] == \
        ["https://arena.ai/1"]
    assert plan.plan_targets([], plan.Search("arena")) == []
    assert plan.plan_targets(None, plan.Search("arena")) == []


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


def test_selector_priority_url_beats_title_pattern():
    """The owner's priority: URL set (alone or both) → the URL pattern decides, and the
    transport is the matched tab's own FULL title — no clipping, ever (the E212 clip is gone).
    """
    long = plan.Target(title="Directly Chat with Frontier Image Generation AI Models — Arena")
    assert plan.selector_for(long, plan.Search("", "arena.ai/image")) == \
        "title=*Directly Chat with Frontier Image Generation AI Models — Arena*"
    assert plan.selector_for(long, plan.Search("anything", "arena.ai/image")) == \
        "title=*Directly Chat with Frontier Image Generation AI Models — Arena*"  # URL wins
    assert plan.selector_for(long, plan.Search("", "")) == \
        "title=*Directly Chat with Frontier Image Generation AI Models — Arena*"  # both blank


def test_selector_title_pattern_alone_is_used_verbatim():
    """A title pattern alone: the user's own words — never the detected title."""
    target = plan.Target(title="Something else entirely")
    assert plan.selector_for(target, plan.Search("arena", "")) == "title=*arena*"
    assert plan.selector_for(target, plan.Search("  arena  ", "")) == "title=*arena*"


def test_selector_is_blank_for_a_titleless_target():
    """No title to carry the selector → blank (unaddressable), never a guess."""
    assert plan.selector_for(plan.Target(), plan.Search("", "arena.ai")) == ""
    assert plan.selector_for(plan.Target(), plan.Search("")) == ""


def test_retitled_keeps_everything_but_the_title():
    target = plan.Target(profile_name="Work", profile_dir="/ff/p1",
                         url="https://x", title="old", windows=((1,),))
    new = plan.retitled(target, "fresh")
    assert new.title == "fresh" and new.profile_name == "Work" and new.url == "https://x"
    assert new.windows == ((1,),) and new.profile_dir == "/ff/p1"


def test_run_label_clips_for_display_only():
    """The report label stays short — the SELECTOR never is (separate concerns)."""
    long = "A" * 90
    clipped = plan.run_label(plan.Target(title=long)).split("“")[1].rstrip("”")
    assert len(clipped) == 40 == plan.TITLE_CLIP
    assert plan.run_label(plan.Target(title="T", profile_name="Work")) == \
        'profile “Work” · tab “T”'
    assert plan.run_label(plan.Target(title="T")) == 'tab “T”'


def test_profile_label_prefers_the_ini_name_then_the_basename():
    assert plan.profile_label("Work", "/ff/p1") == "Work"
    assert plan.profile_label("", "/ff/p2.play") == "p2.play"
    assert plan.profile_label("", "") == ""
    assert plan.profile_label("  ", "") == ""


def test_anonymous_session_wraps_the_flat_rows_seam():
    session = plan.anonymous_session([{"url": "https://x", "title": "X"}])
    assert session["name"] == "" and session["windows"] == []
    assert plan.plan_targets([session], plan.Search("x", ""))[0].url == "https://x"
    assert plan.anonymous_session(None)["rows"] == []


def test_runs_render_selector_profile_args_and_per_run_savelogs(tmp_path):
    """Each planned run: own pattern-built selector, own -P prefix, own savelog file."""
    search = plan.Search("", "arena.ai")
    targets = plan.plan_targets(SESSIONS, search)
    runs = plan.runs(targets, search, tmp_path, "20260923-120000")
    assert [r.index for r in runs] == [1, 2] and runs[0].total == 2
    assert runs[0].selector == "title=*A1*" and runs[1].selector == "title=*B1*"
    assert runs[0].profile_args == ("-P", "Work")          # named → -P name
    assert runs[1].profile_args == ("-profile", "/ff/p2.play")   # unnamed → -profile dir
    assert Path(runs[0].log_path).name == "run-20260923-120000.txt"   # run 1 keeps the plain name
    assert Path(runs[1].log_path).name == "run-20260923-120000-2.txt"  # run 2 never overwrites it
    assert runs[1].label == 'profile “p2.play” · tab “B1”'


def test_runs_fallback_target_uses_the_plain_handoff(tmp_path):
    """No store answer / no match: today's single run — no -P, the title-pattern glob."""
    runs = plan.runs([plan.Target()], plan.Search("arena.ai", ""), tmp_path, "S")
    assert len(runs) == 1
    assert runs[0].profile_args == () and runs[0].selector == "title=*arena.ai*"


def test_summarize_counts_runs_per_profile():
    targets = plan.plan_targets(SESSIONS, plan.Search("", "arena.ai"))
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
