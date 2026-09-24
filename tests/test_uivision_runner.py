"""One framework-test run end to end — provision → foreground → launch → poll.

Every outcome is a distinct answer (RULE 4): ok/error come from the savelog
file, timeout/stopped/blocked name themselves. The seams (stop, sleep, popen)
keep the test off the real desktop; the frozen `time` keeps the log path
predictable.
"""

import itertools
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.browser.uivision import runner
from app.browser.uivision.runner import RunSeams, RunSpec, run_test

pytestmark = pytest.mark.unit

STAMP = "20260922-120000"
OK_LOG = "Status=OK\n###\necho: done — XClick fired (native OS input)"


@pytest.fixture
def frozen_time(monkeypatch):
    monkeypatch.setattr(runner, "time", SimpleNamespace(strftime=lambda fmt: STAMP,
                                                        time=time.time))


OPEN_TABS = [{"url": "https://arena.ai/image/direct?model_a=max", "title": "Arena"}]


async def test_detect_lists_every_tab_and_every_match(tmp_path, frozen_time):
    from app.browser.uivision import runner as runner_mod
    many = [{"url": f"https://arena.ai/page{i}", "title": f"T{i}"} for i in range(3)]
    many.append({"url": "https://other.example", "title": "O"})
    rows, report = reports()
    seams = RunSeams(stop=lambda: True, tabs=lambda: many,
                     addon=lambda: None, probe=lambda: False)
    await runner_mod.run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"),
                              report, seams)
    lines = [m for _s, m, _l in rows]
    assert "firefox open tabs seen: 4" in lines
    assert "firefox tab 1: https://arena.ai/page0 — T0" in lines
    assert "firefox tab 4: https://other.example — O" in lines
    assert "search any title + URL “arena.ai” matches 3 open tab(s):" in lines
    assert "match 3: https://arena.ai/page2" in lines
    assert not any("other.example" in m for m in lines if m.startswith("match"))


async def test_missing_binary_error_names_the_fix_and_the_places(tmp_path, frozen_time):
    rows, report = reports()
    seams = RunSeams(tabs=lambda: [], addon=lambda: None, probe=lambda: False)
    result = await run_test(make_spec(tmp_path), report, seams)
    assert result.kind == "blocked"
    launch_lines = [m for _s, m, _l in rows if "Firefox not found" in m]
    assert launch_lines and "where firefox" in launch_lines[0]
    assert "FULL path" in launch_lines[0]
    assert "Mozilla Firefox" in launch_lines[0] or "/usr/bin/firefox" in launch_lines[0]


async def test_detect_phase_names_tabs_pattern_extension_and_module(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_text(OK_LOG, encoding="utf-8")
    rows, report = reports()
    seams = RunSeams(sleep=noop_sleep, popen=FakePopen(), tabs=lambda: OPEN_TABS,
                     addon=lambda: False, probe=lambda: False)
    await run_test(make_spec(tmp_path, pattern="Arena"), report, seams)
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "firefox open tabs seen: 1" in text
    assert "firefox tab 1: https://arena.ai/image/direct?model_a=max" in text
    assert "search title “Arena” + any URL matches 1 open tab(s):" in text
    assert "match 1: https://arena.ai/image/direct?model_a=max" in text
    assert "extension NOT found" in text
    assert "NOT listening" in text
    levels = {m: l for _s, m, l in rows}
    assert any(l == "warn" for m, l in levels.items() if "NOT listening" in m)


async def test_detect_caps_a_flood_of_tabs(tmp_path, frozen_time):
    many = [{"url": f"https://arena.ai/p{i}", "title": f"T{i}"} for i in range(55)]
    rows, report = reports()
    seams = RunSeams(stop=lambda: True, tabs=lambda: many,
                     addon=lambda: None, probe=lambda: False)
    await run_test(make_spec(tmp_path, pattern="zzz-no-match"), report, seams)
    lines = [m for _s, m, _l in rows]
    assert "firefox open tabs seen: 55" in lines
    assert "firefox tab 50: https://arena.ai/p49 — T49" in lines
    assert "+5 more open tab(s)" in lines
    assert not any(m.startswith("firefox tab 51") for m in lines)


async def test_detect_phase_silent_store_and_blank_pattern(tmp_path, frozen_time):
    rows, report = reports()
    calls = iter(range(10))
    seams = RunSeams(stop=lambda: next(calls) >= 1,   # detect runs, then stop wins
                     tabs=lambda: [], addon=lambda: None, probe=lambda: False)
    result = await run_test(make_spec(tmp_path), report, seams)
    assert result.kind == "stopped"                    # detect ran, stop honoured after
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "open tabs seen: 0" in text and "no session store readable" in text


def make_spec(tmp_path, **over):
    kw = dict(pattern="Arena", url_pattern="", target="xpath=//a[span[text()='New Chat']]",
              macro="Python_XClick_Demo", storage="xfile", home=str(tmp_path / "uivhome"),
              binary=str(tmp_path / "firefox"), timeout_sec=30, pause_ms=1500,
              config_dir=str(tmp_path / "config"))
    kw.update(over)
    return RunSpec(**kw)


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return SimpleNamespace(pid=4321)


def reports():
    rows = []
    return rows, lambda step, message, level="info": rows.append((step, message, level))


async def noop_sleep(_sec):
    pass


async def test_happy_path_xfile(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_text(OK_LOG, encoding="utf-8")           # the extension already answered
    popen = FakePopen()
    rows, report = reports()
    seams = RunSeams(sleep=noop_sleep, popen=popen, tabs=lambda: OPEN_TABS,
                     addon=lambda: True, probe=lambda: True)
    result = await run_test(make_spec(tmp_path), report, seams)

    assert result.kind == "ok" and "macro completed" in result.message
    assert result.lines == ("echo: done — XClick fired (native OS input)",)
    assert [step for step, _msg in result.steps] == ["detect"] * 7 + [
        "provision", "provision", "provision", "foreground",
        "launch", "launch", "result"]

    # the macro landed on the hard drive, XClick-only, reuses the tab, values via cmd vars
    macro_file = tmp_path / "uivhome" / "macros" / "Python_XClick_Demo.json"
    doc = json.loads(macro_file.read_text(encoding="utf-8"))
    assert doc["Name"] == "Python_XClick_Demo"
    assert [c["Command"] for c in doc["Commands"]] == [
        "selectWindow", "bringBrowserToForeground", "executeScript", "XClick", "echo"]
    select_window = doc["Commands"][0]
    assert select_window["Target"] == "${!cmd_var3}" and select_window["Value"] == ""
    for cmd in doc["Commands"]:                       # nothing anywhere opens a page
        assert "open" not in cmd["Command"].lower()
        assert "tab=open" not in cmd["Target"]

    # the launch line: exactly [binary, autorun-url] with the official params
    assert len(popen.calls) == 1
    argv = popen.calls[0]
    assert argv[0] == str(binary) and len(argv) == 2
    url = argv[1]
    assert url.startswith("file://") and "ui.vision.html?" in url
    for param in ("macro=Python_XClick_Demo", "storage=xfile", "direct=1",
                  "savelog=", "cmd_var1=", "cmd_var2=", "cmd_var3=", "closeRPA=1"):
        assert param in url, param
    query = parse_qs(urlsplit(url).query)
    assert query["cmd_var3"] == ["title=*Arena*"]     # the pattern's tab is reused
    assert query["cmd_var1"] == ["1500"]              # the pause budget — not a URL
    assert "arena.ai" not in url                      # the run's URL never opens a page

    # the autorun page exists next to the logs
    assert (tmp_path / "config" / "uivision" / "ui.vision.html").exists()
    # off-Windows the foreground phase warns instead of faking a match (RULE 4)
    foregrounds = [msg for step, msg, _lvl in rows if step == "foreground"]
    assert any("no Firefox window matches" in msg for msg in foregrounds)


async def test_browser_storage_keeps_the_import_artifact_and_hints(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_text("Status=Error: XClick failed\n###\nno target", encoding="utf-8")
    rows, report = reports()
    result = await run_test(make_spec(tmp_path, storage="browser"), report,
                            RunSeams(sleep=noop_sleep, popen=FakePopen()))

    assert result.kind == "error" and result.message == "XClick failed"
    artifact = tmp_path / "config" / "uivision" / "macros" / "Python_XClick_Demo.json"
    assert artifact.exists()
    assert not (tmp_path / "uivhome" / "macros").exists()   # nothing on the hard drive
    assert any("import this macro ONCE" in msg and lvl == "warn"
               for _step, msg, lvl in rows)


async def test_missing_binary_blocks_the_run_before_any_launch(tmp_path, frozen_time):
    popen = FakePopen()
    rows, report = reports()
    result = await run_test(make_spec(tmp_path, binary=str(tmp_path / "no-firefox")), report,
                            RunSeams(sleep=noop_sleep, popen=popen))
    assert result.kind == "blocked"
    assert "not found" in result.message.lower()
    assert popen.calls == []
    assert any(lvl == "error" and "Firefox not found" in msg for _s, msg, lvl in rows)


async def test_bad_macro_name_blocks_provision(tmp_path, frozen_time):
    popen = FakePopen()
    _rows, report = reports()
    result = await run_test(make_spec(tmp_path, macro="bad name"), report,
                            RunSeams(sleep=noop_sleep, popen=popen))
    assert result.kind == "blocked" and "not allowed" in result.message
    assert popen.calls == []
    assert not (tmp_path / "uivhome" / "macros" / "bad name.json").exists()


async def test_stop_before_the_run_leaves_no_files(tmp_path, frozen_time):
    result = await run_test(make_spec(tmp_path), lambda *_a: None, RunSeams(stop=lambda: True))
    assert result.kind == "stopped" and result.message == "stopped before the run began"
    assert result.steps and all(step == "detect" for step, _m in result.steps)
    assert not (tmp_path / "config" / "uivision").exists()


async def test_stop_during_the_poll_ends_the_wait(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    popen = FakePopen()
    checks = itertools.count()
    # checks 1+2 pass (before provision, before launch); check 3 (inside poll) stops
    result = await run_test(make_spec(tmp_path, timeout_sec=300), lambda *_a: None,
                            RunSeams(stop=lambda: next(checks) >= 3,
                                     sleep=noop_sleep, popen=popen))
    assert result.kind == "stopped"
    assert "log file" in result.message
    assert len(popen.calls) == 1                        # the launch still happened


def test_the_fallback_selector_reuses_the_title_pattern_and_never_opens():
    from app.browser.uivision import plan
    assert plan.selector_for(plan.Target(), "Arena") == "title=*Arena*"
    assert plan.selector_for(plan.Target(), "  Agent Arena  ") == "title=*Agent Arena*"
    assert plan.selector_for(plan.Target(), "") == ""   # blank = no selector, not tab=open


async def test_both_patterns_blank_runs_every_open_tab_behind_a_warning(
        tmp_path, frozen_time):
    """The owner's rule: blank = any — the macro runs on every open tab, loudly."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_text(OK_LOG, encoding="utf-8")
    popen = FakePopen()
    rows, report = reports()
    result = await run_test(make_spec(tmp_path, pattern="", target="css=#go"), report,
                            RunSeams(sleep=noop_sleep, popen=popen, tabs=lambda: OPEN_TABS,
                                     addon=lambda: True, probe=lambda: True))
    assert result.kind == "ok"
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "both patterns are empty — the macro will run on EVERY open tab (1 tab(s))" in text
    assert popen.calls == [[str(binary), popen.calls[0][1]]]


async def test_both_patterns_blank_and_no_tabs_blocks_before_any_file(tmp_path, frozen_time):
    popen = FakePopen()
    rows, report = reports()
    result = await run_test(make_spec(tmp_path, pattern="  "), report,
                            RunSeams(sleep=noop_sleep, popen=popen, tabs=lambda: [],
                                     addon=lambda: True, probe=lambda: True))
    assert result.kind == "blocked"
    assert "no tab-title and no URL pattern" in result.message
    assert "nothing opened" in result.message
    assert popen.calls == []                          # Firefox never even started
    assert not (tmp_path / "config" / "uivision").exists()    # nothing provisioned
    assert any(step == "launch" and lvl == "error" for step, _msg, lvl in rows)


async def test_refused_launch_blocks_with_the_cause_not_a_crash(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")

    def refuse(_argv):
        raise PermissionError("[WinError 5] Access is denied")

    rows, report = reports()
    result = await run_test(make_spec(tmp_path), report,
                            RunSeams(sleep=noop_sleep, popen=refuse, tabs=lambda: OPEN_TABS,
                                     addon=lambda: True, probe=lambda: True))
    assert result.kind == "blocked"
    assert "would not start" in result.message
    assert "WinError 5" in result.message
    assert any(step == "launch" and lvl == "error" and "would not start" in msg
               for step, msg, lvl in rows)


async def test_windows_seam_reports_each_window_and_targets_the_tab(
        tmp_path, frozen_time, monkeypatch):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_text(OK_LOG, encoding="utf-8")
    seen = {}

    def fake_mapping(pattern, windows):
        seen["pattern"], seen["windows"] = pattern, windows
        return ([(11, "Arena — Mozilla Firefox")], 1)

    monkeypatch.setattr(runner.desktop, "foreground_tab_window", fake_mapping)
    rows, report = reports()
    windows = [{"index": 1, "active": {"url": "https://arena.ai/x", "title": "Arena"},
                "tabs": [{"url": "https://arena.ai/x", "title": "Arena"},
                         {"url": "https://example.com", "title": "Ex"}]}]
    seams = RunSeams(sleep=noop_sleep, popen=FakePopen(), tabs=lambda: OPEN_TABS,
                     addon=lambda: True, probe=lambda: True, windows=lambda: windows)
    result = await run_test(make_spec(tmp_path), report, seams)
    assert result.kind == "ok"
    assert seen["pattern"] == "Arena" and seen["windows"] == windows
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "firefox window 1: 2 tab(s) — active “Arena”" in text
    assert "holds the tab matching “Arena”" in text


async def test_timeout_when_the_savelog_never_answers(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    result = await run_test(make_spec(tmp_path, timeout_sec=0), lambda *_a: None,
                            RunSeams(sleep=noop_sleep, popen=FakePopen()))
    assert result.kind == "timeout"
    assert "deadline" in result.message


# ── multi-profile (2026-09-23 owner fix): every profile, every matching tab ──

PROFILES = [
    {"name": "Work", "dir": "/ff/p1.work", "rows": [
        {"url": "https://arena.ai/a", "title": "A1"},
        {"url": "https://other.example", "title": "O"}],
     "windows": [{"index": 1, "active": {"url": "https://arena.ai/a", "title": "A1"},
                  "tabs": [{"url": "https://arena.ai/a", "title": "A1"}]}],
     "source": "recovery.jsonlz4", "stamp": 2.0},
    {"name": "", "dir": "/ff/p2.play", "rows": [
        {"url": "https://arena.ai/b", "title": "B1"}],
     "windows": [{"index": 1, "active": {"url": "https://arena.ai/b", "title": "B1"},
                  "tabs": [{"url": "https://arena.ai/b", "title": "B1"}]}],
     "source": "recovery.jsonlz4", "stamp": 9.0},
]


def profile_seams(popen, logs_ready=False):
    return RunSeams(sleep=noop_sleep, popen=popen, profiles=lambda: PROFILES,
                    addon=lambda: True, probe=lambda: True)


def write_logs(tmp_path, names):
    for name in names:
        log = tmp_path / "config" / "uivision" / "logs" / name
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(OK_LOG, encoding="utf-8")


async def test_two_profiles_get_one_run_each_in_their_own_instance(tmp_path, frozen_time):
    """Two profiles, one matching tab each → two launches, each -P/-profile-addressed."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    popen = FakePopen()
    rows, report = reports()
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), report,
                            profile_seams(popen))
    assert result.kind == "ok" and result.message == "all 2 run(s) ok"
    assert len(popen.calls) == 2

    first, second = popen.calls
    assert first[:3] == [str(binary), "-P", "Work"]          # named profile → -P name
    assert second[:3] == [str(binary), "-profile", "/ff/p2.play"]   # unnamed → -profile dir
    for argv in (first, second):
        assert len(argv) == 4 and argv[-1].startswith("file://")

    q1 = parse_qs(urlsplit(first[3]).query)
    q2 = parse_qs(urlsplit(second[3]).query)
    assert q1["cmd_var3"] == ["title=*A1*"]                  # THIS profile's tab
    assert q2["cmd_var3"] == ["title=*B1*"]                  # not the pattern's first match
    assert q1["savelog"][0].endswith(f"run-{STAMP}.txt")
    assert q2["savelog"][0].endswith(f"run-{STAMP}-2.txt")   # run 2 never overwrites run 1


async def test_detect_names_every_profile_and_the_run_plan(tmp_path, frozen_time):
    rows, report = reports()
    seams = RunSeams(stop=lambda: True, profiles=lambda: PROFILES,
                     addon=lambda: None, probe=lambda: False)
    await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), report, seams)
    text = [m for _s, m, _l in rows]
    assert "firefox open tabs seen: 3" in text
    assert ('search any title + URL “arena.ai” — 2 open tab(s) match in '
            '2 profile(s): Work, p2.play') in text
    assert 'match 1: https://arena.ai/a — A1 (profile “Work”)' in text
    assert 'match 2: https://arena.ai/b — B1 (profile “p2.play”)' in text
    assert 'run plan: 2 macro run(s) — “Work” ×1, “p2.play” ×1' in text
    assert 'firefox window 1 (profile “Work”): 1 tab(s) — active “A1”' in text
    assert 'firefox window 1 (profile “p2.play”): 1 tab(s) — active “B1”' in text


async def test_second_tab_of_one_profile_gets_its_own_run(tmp_path, frozen_time):
    """Two matching tabs in ONE profile → two runs, each its own title selector."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    one = [{"name": "Work", "dir": "/ff/p1.work", "rows": [
        {"url": "https://arena.ai/1", "title": "First"},
        {"url": "https://arena.ai/2", "title": "Second"}], "windows": [],
        "source": "", "stamp": 1.0}]
    popen = FakePopen()
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            RunSeams(sleep=noop_sleep, popen=popen,
                                     profiles=lambda: one, addon=lambda: True,
                                     probe=lambda: True))
    assert result.kind == "ok"
    assert [parse_qs(urlsplit(call[3]).query)["cmd_var3"][0] for call in popen.calls] == [
        "title=*First*", "title=*Second*"]
    assert all(call[1:3] == ["-P", "Work"] for call in popen.calls)


async def test_duplicate_titles_warn_that_runs_share_the_first_tab(tmp_path, frozen_time):
    same = [{"name": "Work", "dir": "/ff/p1", "rows": [
        {"url": "https://arena.ai/1", "title": "Same"},
        {"url": "https://arena.ai/2", "title": "Same"}], "windows": [],
        "source": "", "stamp": 1.0}]
    rows, report = reports()
    seams = RunSeams(stop=lambda: True, profiles=lambda: same,
                     addon=lambda: None, probe=lambda: False)
    await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), report, seams)
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "cannot tell them apart" in text
    assert any(lvl == "warn" for s, _m, lvl in rows if "cannot tell them apart" in _m)


async def test_mixed_verdicts_roll_up_with_the_counts(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    logs = tmp_path / "config" / "uivision" / "logs"
    logs.mkdir(parents=True)
    (logs / f"run-{STAMP}.txt").write_text(OK_LOG, encoding="utf-8")
    (logs / f"run-{STAMP}-2.txt").write_text("Status=Error: XClick failed\n###\nno target",
                                             encoding="utf-8")
    popen = FakePopen()
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            profile_seams(popen))
    assert result.kind == "error"
    assert result.message == ("1/2 run(s) ok — profile “p2.play” · tab “B1”"
                              ": XClick failed")
    assert "— run 2/2" in result.lines[2]                    # per-run headings ride the log


async def test_stop_between_runs_names_the_progress(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    popen = FakePopen()
    checks = itertools.count(1)                        # 1-based: fires on the 3rd check
    # 1: after detect, 2: before run 1 — the 3rd check (before run 2) stops
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            RunSeams(stop=lambda: next(checks) >= 3, sleep=noop_sleep,
                                     popen=popen, profiles=lambda: PROFILES,
                                     addon=lambda: True, probe=lambda: True))
    assert result.kind == "stopped"
    assert result.message == "stopped after 1 of 2 run(s) — macro completed"
    assert len(popen.calls) == 1                             # run 2 never launched


async def test_refused_launch_aborts_the_rest_and_says_so(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")

    def refuse(_argv):
        raise PermissionError("[WinError 5] Access is denied")

    popen = refuse
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            profile_seams(popen))
    assert result.kind == "blocked"
    assert "WinError 5" in result.message and "not attempted" in result.message


async def test_no_profiles_answer_falls_back_to_todays_single_run(tmp_path, frozen_time):
    """Empty store answer → the plain handoff: [binary, url], the title-pattern glob."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_text(OK_LOG, encoding="utf-8")
    popen = FakePopen()
    result = await run_test(make_spec(tmp_path, pattern="arena.ai"), lambda *_a: None,
                            RunSeams(sleep=noop_sleep, popen=popen,
                                     profiles=lambda: [], addon=lambda: True,
                                     probe=lambda: True))
    assert result.kind == "ok"
    assert popen.calls == [[str(binary), popen.calls[0][1]]]
    assert len(popen.calls[0]) == 2                          # exactly [binary, url]
    q = parse_qs(urlsplit(popen.calls[0][1]).query)
    assert q["cmd_var3"] == ["title=*arena.ai*"]             # the pattern, untargeted


async def test_stop_inside_a_poll_rolls_up_stopped(tmp_path, frozen_time):
    """A poll that answers 'stopped' mid-sequence: the roll-up names the progress."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    popen = FakePopen()
    checks = itertools.count(1)                # 1: after detect, 2: loop top — 3: in poll
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            RunSeams(stop=lambda: next(checks) >= 3, sleep=noop_sleep,
                                     popen=popen, profiles=lambda: PROFILES,
                                     addon=lambda: True, probe=lambda: True))
    assert result.kind == "stopped"
    assert result.message == ("stopped after 1 of 2 run(s) — stopped before the log "
                              "file answered")
    assert len(popen.calls) == 1


async def test_foreground_with_window_matches_reports_the_raise(tmp_path, frozen_time,
                                                                monkeypatch):
    """Plain title matches found on the desktop: the raise is reported per run."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_text(OK_LOG, encoding="utf-8")
    monkeypatch.setattr(runner.desktop, "foreground",
                        lambda pattern: ([(7, "Arena — Mozilla Firefox")], 1))
    rows, report = reports()
    result = await run_test(make_spec(tmp_path), report,
                            RunSeams(sleep=noop_sleep, popen=FakePopen(),
                                     tabs=lambda: OPEN_TABS, addon=lambda: True,
                                     probe=lambda: True))
    assert result.kind == "ok"
    foregrounds = [msg for step, msg, _lvl in rows if step == "foreground"]
    assert any("1/1 Firefox window(s) on top — Arena — Mozilla Firefox" in msg
               for msg in foregrounds)


async def test_real_store_path_reports_profiles_source_and_profile_windows(
        tmp_path, frozen_time, monkeypatch):
    """The real eyes (no seams): the profile scan, the store receipt, the windows."""
    sessions = [{"name": "Work", "dir": "/ff/p1.work", "rows": [
        {"url": "https://arena.ai/a", "title": "A1"}],
        "windows": [{"index": 1, "active": {"url": "https://arena.ai/a", "title": "A1"},
                     "tabs": [{"url": "https://arena.ai/a", "title": "A1"}]}],
        "source": "recovery.jsonlz4", "stamp": 5.0}]
    monkeypatch.setattr(runner.tabs, "profile_sessions", lambda: sessions)
    monkeypatch.setattr(runner.tabs, "profile_dirs", lambda: [])
    monkeypatch.setattr(runner.desktop, "foreground_tab_window", lambda *a: None)
    monkeypatch.setattr(runner.desktop, "foreground", lambda pattern: ([], 0))
    rows, report = reports()
    seams = RunSeams(stop=lambda: True, addon=lambda: True, probe=lambda: False)
    await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), report, seams)
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "firefox profiles scanned: 0 (is Firefox installed?)" in text
    assert "session source: recovery.jsonlz4 in Work" in text
    assert 'firefox window 1 (profile “Work”): 1 tab(s) — active “A1”' in text
    assert "firefox open tabs seen: 1" in text


# ── URL-pattern search (2026-09-24 owner option): blank means any, on both ──

URL_ONLY = [
    {"name": "Work", "dir": "/ff/p1.work", "rows": [
        {"url": "https://arena.ai/image/1", "title": "Image One"},
        {"url": "https://other.example", "title": "O"}],
     "windows": [], "source": "", "stamp": 2.0},
    {"name": "", "dir": "/ff/p2.play", "rows": [
        {"url": "https://arena.ai/image/2", "title": "Image Two"}],
     "windows": [], "source": "", "stamp": 9.0},
]


def url_seams(popen):
    return RunSeams(sleep=noop_sleep, popen=popen, profiles=lambda: URL_ONLY,
                    addon=lambda: True, probe=lambda: True)


async def test_url_pattern_runs_one_macro_per_matching_tab_across_profiles(
        tmp_path, frozen_time):
    """URL-only search: both profiles' matching tabs run, selected by their titles."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    popen = FakePopen()
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai/image/"),
                            lambda *_a: None, url_seams(popen))
    assert result.kind == "ok" and result.message == "all 2 run(s) ok"
    first, second = popen.calls
    assert first[1:3] == ["-P", "Work"] and second[1:3] == ["-profile", "/ff/p2.play"]
    selectors = [parse_qs(urlsplit(a[3]).query)["cmd_var3"][0] for a in popen.calls]
    assert selectors == ["title=*Image One*", "title=*Image Two*"]   # tab's OWN title
    assert all("cmd_var1=" in a[3] and "savelog=" in a[3] for a in popen.calls)


async def test_url_search_reports_its_filters_and_warns_when_unmapped(
        tmp_path, frozen_time):
    """The detect lines name the URL filter; off-Windows the foreground says so."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    rows, report = reports()
    await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai/image/"),
                   report, url_seams(FakePopen()))
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert ('search any title + URL “arena.ai/image/” — 2 open tab(s) match in '
            '2 profile(s): Work, p2.play') in text
    assert 'run plan: 2 macro run(s) — “Work” ×1, “p2.play” ×1' in text
    assert 'no Firefox window matches “arena.ai/image/”' in text    # the URL needle


async def test_title_and_url_patterns_combine_and_cut_the_matches(tmp_path, frozen_time):
    """Both patterns: only tabs passing BOTH filters run."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    popen = FakePopen()
    result = await run_test(make_spec(tmp_path, pattern="Image One",
                                      url_pattern="arena.ai/image/"),
                            lambda *_a: None, url_seams(popen))
    assert result.kind == "ok"
    assert len(popen.calls) == 1                                   # only "Image One" ran
    assert parse_qs(urlsplit(popen.calls[0][3]).query)["cmd_var3"] == ["title=*Image One*"]


async def test_url_only_search_with_no_match_blocks_by_name(tmp_path, frozen_time):
    """A URL-only search cannot build a fallback selector — blocked, not E210-guessed."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    popen = FakePopen()
    rows, report = reports()
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="no-such.example"),
                            report, RunSeams(sleep=noop_sleep, popen=popen,
                                             profiles=lambda: URL_ONLY,
                                             addon=lambda: True, probe=lambda: True))
    assert result.kind == "blocked"
    assert "no-such.example" in result.message and "title" in result.message
    assert popen.calls == []
    assert not (tmp_path / "config" / "uivision").exists()          # blocked before provision
    assert any(lvl == "warn" and "no OPEN tab matches" in msg for _s, msg, lvl in rows)


async def test_titleless_url_match_is_skipped_with_a_warning(tmp_path, frozen_time):
    """A matched tab without a title cannot be selected — warned, others still run."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    popen = FakePopen()
    rows, report = reports()
    sessions = [{"name": "Work", "dir": "/ff/p1", "rows": [
        {"url": "https://arena.ai/image/blank", "title": ""},
        {"url": "https://arena.ai/image/titled", "title": "Titled"}],
        "windows": [], "source": "", "stamp": 1.0}]
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai/image/"),
                            report, RunSeams(sleep=noop_sleep, popen=popen,
                                             profiles=lambda: sessions,
                                             addon=lambda: True, probe=lambda: True))
    assert result.kind == "ok"
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "matched but has no TITLE" in text
    assert "warn" in [lvl for s, _m, lvl in rows if "no TITLE" in _m]
    assert len(popen.calls) == 1                                    # only the titled tab
    assert parse_qs(urlsplit(popen.calls[0][3]).query)["cmd_var3"] == ["title=*Titled*"]


async def test_selected_profiles_filtering(tmp_path, frozen_time):
    """selected_profiles limits target discovery to only the checked profiles."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    popen = FakePopen()
    spec = make_spec(tmp_path, pattern="", url_pattern="arena.ai/image/",
                     selected_profiles=("Work",))
    result = await run_test(spec, lambda *_a: None, url_seams(popen))
    assert result.kind == "ok"
    assert len(popen.calls) == 1
    assert popen.calls[0][1:3] == ["-P", "Work"]


async def test_missing_tab_skip_enabled(tmp_path, frozen_time):
    """skip_missing_tab=True skips profile without matching tab immediately."""
    sessions = [{"name": "EmptyProf", "dir": "/ff/empty", "rows": [], "windows": []}]
    rows, report = reports()
    spec = make_spec(tmp_path, pattern="NoSuchTab", selected_profiles=("EmptyProf",),
                     skip_missing_tab=True)
    seams = RunSeams(sleep=noop_sleep, popen=FakePopen(), profiles=lambda: sessions,
                     addon=lambda: True, probe=lambda: True)
    result = await run_test(spec, report, seams)
    assert any("skipping profile" in m for _s, m, _l in rows)


async def test_missing_tab_wait_timeout(tmp_path, frozen_time, monkeypatch):
    """skip_missing_tab=False waits up to 60s (faked by clock) then skips."""
    sessions = [{"name": "EmptyProf", "dir": "/ff/empty", "rows": [], "windows": []}]
    rows, report = reports()
    spec = make_spec(tmp_path, pattern="NoSuchTab", selected_profiles=("EmptyProf",),
                     skip_missing_tab=False)
    clock = [100.0]
    monkeypatch.setattr(runner.time, "time", lambda: clock[0])
    async def fast_sleep(sec):
        clock[0] += 70.0
    seams = RunSeams(sleep=fast_sleep, popen=FakePopen(), profiles=lambda: sessions,
                     addon=lambda: True, probe=lambda: True)
    result = await run_test(spec, report, seams)
    assert any("waiting up to 60s" in m for _s, m, _l in rows)
    assert any("60s expired" in m for _s, m, _l in rows)

