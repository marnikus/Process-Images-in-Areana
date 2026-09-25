"""One framework-test run end to end — resolve → deliver → poll, one run per profile.

Every outcome is a distinct answer (RULE 4): ok/error come from the savelog
file, timeout/stopped/blocked/skipped name themselves. The seams (stop, sleep,
popen, os_windows, deliver) keep the test off the real desktop; the frozen
`time` keeps the log path predictable; `no_rescan_wait` skips the 20 s
flush-wait in tests that never match.
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


@pytest.fixture
def no_rescan_wait(monkeypatch):
    """Instant rescan budget — no-match tests skip the 20 s flush wait."""
    monkeypatch.setattr(runner, "RESCAN_BUDGET_SEC", 0)


OPEN_TABS = [{"url": "https://arena.ai/image/direct?model_a=max", "title": "Arena"}]


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


class FakeDeliver:
    """The address-bar keys as a script: records (hwnd, url), or refuses."""

    def __init__(self, refuse=False):
        self.calls = []
        self.attempts = 0
        self._refuse = refuse

    def __call__(self, hwnd, url):
        from app.browser.uivision.delivery import DeliveryError
        self.attempts += 1
        if self._refuse:
            raise DeliveryError("SendInput failed")
        self.calls.append((hwnd, url))


def reports():
    rows = []
    return rows, lambda step, message, level="info": rows.append((step, message, level))


async def noop_sleep(_sec):
    pass


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


async def test_missing_binary_error_names_the_fix_and_the_places(
        tmp_path, frozen_time, no_rescan_wait):
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
                     sleep=noop_sleep,                # the rescan slice never really sleeps
                     tabs=lambda: [], addon=lambda: None, probe=lambda: False)
    result = await run_test(make_spec(tmp_path), report, seams)
    assert result.kind == "stopped"                    # detect ran, stop honoured after
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "open tabs seen: 0" in text and "no session store readable" in text


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
    # the aim is announced, the window raised, then the launch lines follow
    assert [step for step, _msg in result.steps] == ["detect"] * 7 + [
        "provision", "provision", "provision", "launch", "foreground",
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

    # the launch line: [binary, -new-tab, autorun-url] with the official params
    assert len(popen.calls) == 1
    argv = popen.calls[0]
    assert argv[0] == str(binary) and argv[1] == "-new-tab" and len(argv) == 3
    url = argv[2]
    assert url.startswith("file://") and "ui.vision.html?" in url
    for param in ("macro=Python_XClick_Demo", "storage=xfile", "direct=1",
                  "savelog=", "cmd_var1=", "cmd_var2=", "cmd_var3=", "closeRPA=1"):
        assert param in url, param
    query = parse_qs(urlsplit(url).query)
    assert query["cmd_var3"] == ["title=*Arena*"]     # the pattern's tab is reused
    assert query["cmd_var1"] == ["1500"]              # the pause budget — not a URL
    assert "arena.ai" not in url                      # the run's URL never opens a page
    addressing = [m for s, m, _l in rows if s == "launch" and m.startswith("addressing")]
    assert addressing == ["addressing title=*Arena*"]  # the aiming is on the record

    # the autorun page exists next to the logs
    assert (tmp_path / "config" / "uivision" / "ui.vision.html").exists()
    # off-Windows the foreground phase warns instead of faking a match (RULE 4)
    foregrounds = [msg for step, msg, _lvl in rows if step == "foreground"]
    assert any("no Firefox window matches" in msg for msg in foregrounds)
    # the protected-tab check stays silent — every pre-existing tab survived
    assert not any("no longer in the session store" in msg for _s, msg, _l in rows)


async def test_browser_storage_keeps_the_import_artifact_and_hints(
        tmp_path, frozen_time, no_rescan_wait):
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


async def test_missing_binary_blocks_the_run_before_any_launch(
        tmp_path, frozen_time, no_rescan_wait):
    popen = FakePopen()
    rows, report = reports()
    result = await run_test(make_spec(tmp_path, binary=str(tmp_path / "no-firefox")), report,
                            RunSeams(sleep=noop_sleep, popen=popen))
    assert result.kind == "blocked"
    assert "not found" in result.message.lower()
    assert popen.calls == []
    assert any(lvl == "error" and "Firefox not found" in msg for _s, msg, lvl in rows)


async def test_bad_macro_name_blocks_provision(tmp_path, frozen_time, no_rescan_wait):
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
                                     sleep=noop_sleep, popen=popen, tabs=lambda: OPEN_TABS))
    assert result.kind == "stopped"
    assert "log file" in result.message
    assert len(popen.calls) == 1                        # the launch still happened


def test_the_fallback_selector_reuses_the_title_pattern_and_never_opens():
    from app.browser.uivision import plan
    assert plan.selector_for("Arena") == "title=*Arena*"
    assert plan.selector_for("  Agent Arena  ") == "title=*Agent Arena*"
    assert plan.selector_for("") == ""   # blank = launch resolves a tab=N, never tab=open


async def test_both_patterns_blank_addresses_the_first_match_per_profile(
        tmp_path, frozen_time):
    """The owner's rule: blank = any — each profile runs its first match, loudly."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_text(OK_LOG, encoding="utf-8")
    popen = FakePopen()
    rows, report = reports()
    one = [{"name": "Work", "dir": "/ff/p1.work",
            "rows": [{"url": "https://arena.ai/a", "title": "A1"}],
            "windows": [{"index": 1, "active": {"url": "https://arena.ai/a", "title": "A1"},
                         "tabs": [{"url": "https://arena.ai/a", "title": "A1"}]}],
            "source": "", "stamp": 1.0}]
    result = await run_test(make_spec(tmp_path, pattern="", target="css=#go"), report,
                            RunSeams(sleep=noop_sleep, popen=popen, profiles=lambda: one,
                                     addon=lambda: True, probe=lambda: True,
                                     os_windows=lambda: []))
    assert result.kind == "ok"
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert ("both patterns are empty — the run addresses the FIRST match in every "
            "profile (1 profile(s))") in text
    assert popen.calls == [[str(binary), "-P", "Work", "-new-tab", popen.calls[0][4]]]
    query = parse_qs(urlsplit(popen.calls[0][4]).query)
    assert query["cmd_var3"] == ["tab=-1"]            # first of one, resolved at launch


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


async def test_timeout_when_the_savelog_never_answers(tmp_path, frozen_time, no_rescan_wait):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    result = await run_test(make_spec(tmp_path, timeout_sec=0), lambda *_a: None,
                            RunSeams(sleep=noop_sleep, popen=FakePopen()))
    assert result.kind == "timeout"
    assert "deadline" in result.message

# ── multi-profile (2026-09-23 owner fix; 2026-09-24: one run per profile) ──

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


def profile_seams(popen, os_windows=None, deliver=None):
    return RunSeams(sleep=noop_sleep, popen=popen, profiles=lambda: PROFILES,
                    addon=lambda: True, probe=lambda: True,
                    os_windows=os_windows, deliver=deliver)


def write_logs(tmp_path, names):
    for name in names:
        log = tmp_path / "config" / "uivision" / "logs" / name
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(OK_LOG, encoding="utf-8")


async def test_two_profiles_get_one_run_each_through_their_own_window(
        tmp_path, frozen_time):
    """Two profiles, one matching tab each → two address-bar deliveries, no process."""
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    popen = FakePopen()
    deliver = FakeDeliver()
    rows, report = reports()
    seen = [(11, "A1 — Mozilla Firefox"), (22, "B1 — Mozilla Firefox")]
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), report,
                            profile_seams(popen, os_windows=lambda: seen, deliver=deliver))
    assert result.kind == "ok" and result.message == "all 2 run(s) ok"
    assert popen.calls == []                              # address-bar: no new process
    assert [hwnd for hwnd, _url in deliver.calls] == [11, 22]   # each profile's window

    q1 = parse_qs(urlsplit(deliver.calls[0][1]).query)
    q2 = parse_qs(urlsplit(deliver.calls[1][1]).query)
    assert q1["cmd_var3"] == ["tab=-1"]                  # THIS profile's tab, by index
    assert q2["cmd_var3"] == ["tab=-1"]
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


async def test_crowded_profile_runs_its_first_match_once(tmp_path, frozen_time):
    """Two matching tabs in ONE profile → ONE run addressing the first, warned."""
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    deliver = FakeDeliver()
    rows, report = reports()
    one = [{"name": "Work", "dir": "/ff/p1.work",
            "rows": [{"url": "https://arena.ai/1", "title": "First"},
                     {"url": "https://arena.ai/2", "title": "Second"}],
            "windows": [{"index": 1, "active": {"url": "https://arena.ai/1", "title": "First"},
                         "tabs": [{"url": "https://arena.ai/1", "title": "First"},
                                  {"url": "https://arena.ai/2", "title": "Second"}]}],
            "source": "", "stamp": 1.0}]
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), report,
                            RunSeams(sleep=noop_sleep, popen=FakePopen(),
                                     profiles=lambda: one,
                                     addon=lambda: True, probe=lambda: True,
                                     os_windows=lambda: [(11, "First — Mozilla Firefox")],
                                     deliver=deliver))
    assert result.kind == "ok"
    assert len(deliver.calls) == 1
    assert parse_qs(urlsplit(deliver.calls[0][1]).query)["cmd_var3"] == ["tab=-2"]
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "2 tab(s) match — the run addresses the first" in text
    assert "narrow the pattern" in text


async def test_crowded_profile_warns_to_narrow_the_pattern(tmp_path, frozen_time):
    same = [{"name": "Work", "dir": "/ff/p1", "rows": [
        {"url": "https://arena.ai/1", "title": "Same"},
        {"url": "https://arena.ai/2", "title": "Same"}], "windows": [],
        "source": "", "stamp": 1.0}]
    rows, report = reports()
    seams = RunSeams(stop=lambda: True, profiles=lambda: same,
                     addon=lambda: None, probe=lambda: False)
    await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), report, seams)
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "2 tab(s) match — the run addresses the first" in text
    assert "narrow the pattern" in text
    assert any(lvl == "warn" for s, _m, lvl in rows if "narrow the pattern" in _m)


async def test_mixed_verdicts_roll_up_with_the_counts(tmp_path, frozen_time):
    logs = tmp_path / "config" / "uivision" / "logs"
    logs.mkdir(parents=True)
    (logs / f"run-{STAMP}.txt").write_text(OK_LOG, encoding="utf-8")
    (logs / f"run-{STAMP}-2.txt").write_text("Status=Error: XClick failed\n###\nno target",
                                             encoding="utf-8")
    popen = FakePopen()
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            profile_seams(popen, os_windows=lambda: []))
    assert result.kind == "error"
    assert result.message == ("1/2 run(s) ok — profile “p2.play” · tab “B1”"
                              ": XClick failed")
    assert "— run 2/2" in result.lines[2]                    # per-run headings ride the log


async def test_stop_between_runs_names_the_progress(tmp_path, frozen_time):
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    deliver = FakeDeliver()
    checks = itertools.count(1)                        # 1-based: fires on the 3rd check
    seen = [(11, "A1 — Mozilla Firefox"), (22, "B1 — Mozilla Firefox")]
    # 1: after detect, 2: before run 1 — the 3rd check (before run 2) stops
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            RunSeams(stop=lambda: next(checks) >= 3, sleep=noop_sleep,
                                     popen=FakePopen(), profiles=lambda: PROFILES,
                                     addon=lambda: True, probe=lambda: True,
                                     os_windows=lambda: seen, deliver=deliver))
    assert result.kind == "stopped"
    assert result.message == "stopped after 1 of 2 run(s) — macro completed"
    assert len(deliver.calls) == 1                             # run 2 never delivered


async def test_refused_cold_start_blocks_with_the_cause(tmp_path, frozen_time):
    """A lone profile with nothing running cold-starts — a refusal names its cause."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")

    def refuse(_argv):
        raise PermissionError("[WinError 5] Access is denied")

    one = [dict(PROFILES[0])]
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            RunSeams(sleep=noop_sleep, popen=refuse, profiles=lambda: one,
                                     addon=lambda: True, probe=lambda: True,
                                     os_windows=lambda: []))
    assert result.kind == "blocked"
    assert "WinError 5" in result.message


async def test_no_profiles_answer_falls_back_to_todays_single_run(
        tmp_path, frozen_time, no_rescan_wait):
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
    assert popen.calls == [[str(binary), "-new-tab", popen.calls[0][2]]]
    assert len(popen.calls[0]) == 3                          # exactly [binary, -new-tab, url]
    q = parse_qs(urlsplit(popen.calls[0][2]).query)
    assert q["cmd_var3"] == ["title=*arena.ai*"]             # the pattern, untargeted


async def test_stop_inside_a_poll_rolls_up_stopped(tmp_path, frozen_time):
    """A poll that answers 'stopped' mid-sequence: the roll-up names the progress."""
    deliver = FakeDeliver()
    checks = itertools.count(1)                # 1: after detect, 2: loop top — 3: in poll
    seen = [(11, "A1 — Mozilla Firefox"), (22, "B1 — Mozilla Firefox")]
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai"), lambda *_a: None,
                            RunSeams(stop=lambda: next(checks) >= 3, sleep=noop_sleep,
                                     popen=FakePopen(), profiles=lambda: PROFILES,
                                     addon=lambda: True, probe=lambda: True,
                                     os_windows=lambda: seen, deliver=deliver))
    assert result.kind == "stopped"
    assert result.message == ("stopped after 1 of 2 run(s) — stopped before the log "
                              "file answered")
    assert len(deliver.calls) == 1


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
     "windows": [{"index": 1, "active": {"url": "https://arena.ai/image/1", "title": "Image One"},
                  "tabs": [{"url": "https://arena.ai/image/1", "title": "Image One"},
                           {"url": "https://other.example", "title": "O"}]}],
     "source": "", "stamp": 2.0},
    {"name": "", "dir": "/ff/p2.play", "rows": [
        {"url": "https://arena.ai/image/2", "title": "Image Two"}],
     "windows": [{"index": 1, "active": {"url": "https://arena.ai/image/2", "title": "Image Two"},
                  "tabs": [{"url": "https://arena.ai/image/2", "title": "Image Two"}]}],
     "source": "", "stamp": 9.0},
]


def url_seams(popen, os_windows=None, deliver=None):
    return RunSeams(sleep=noop_sleep, popen=popen, profiles=lambda: URL_ONLY,
                    addon=lambda: True, probe=lambda: True,
                    os_windows=os_windows, deliver=deliver)


async def test_url_search_runs_each_profile_once_by_index(tmp_path, frozen_time):
    """URL-only search: one run per profile, addressed by a fresh tab=N."""
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    popen = FakePopen()
    deliver = FakeDeliver()
    seen = [(11, "Image One — Mozilla Firefox"), (22, "Image Two — Mozilla Firefox")]
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai/image/"),
                            lambda *_a: None,
                            url_seams(popen, os_windows=lambda: seen, deliver=deliver))
    assert result.kind == "ok" and result.message == "all 2 run(s) ok"
    assert popen.calls == []                              # address-bar: no new process
    assert [hwnd for hwnd, _url in deliver.calls] == [11, 22]
    selectors = [parse_qs(urlsplit(url).query)["cmd_var3"][0]
                 for _hwnd, url in deliver.calls]
    assert selectors == ["tab=-2", "tab=-1"]   # first of two, then the single tab
    assert all("cmd_var1=" in url and "savelog=" in url for _hwnd, url in deliver.calls)


async def test_url_search_reports_its_filters_and_warns_when_unmapped(
        tmp_path, frozen_time):
    """The detect lines name the URL filter; nothing running stays manual, loudly."""
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    rows, report = reports()
    await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai/image/"),
                   report, url_seams(FakePopen(), os_windows=lambda: []))
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert ('search any title + URL “arena.ai/image/” — 2 open tab(s) match in '
            '2 profile(s): Work, p2.play') in text
    assert 'run plan: 2 macro run(s) — “Work” ×1, “p2.play” ×1' in text
    assert 'no Firefox window matches “arena.ai/image/”' in text    # the URL needle
    assert "2 profiles match" in text                    # the manual reason (nothing runs)


async def test_title_and_url_patterns_combine_and_cut_the_matches(tmp_path, frozen_time):
    """Both patterns: only tabs passing BOTH filters run."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    popen = FakePopen()
    result = await run_test(make_spec(tmp_path, pattern="Image One",
                                      url_pattern="arena.ai/image/"),
                            lambda *_a: None,
                            url_seams(popen, os_windows=lambda: []))
    assert result.kind == "ok"
    assert len(popen.calls) == 1                                   # only "Image One" ran
    assert parse_qs(urlsplit(popen.calls[0][-1]).query)["cmd_var3"] == ["title=*Image One*"]


async def test_url_only_search_with_no_match_blocks_by_name(
        tmp_path, frozen_time, no_rescan_wait):
    """A URL-only search with no match blocks — there is nothing to aim at."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    popen = FakePopen()
    rows, report = reports()
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="no-such.example"),
                            report, RunSeams(sleep=noop_sleep, popen=popen,
                                             profiles=lambda: URL_ONLY,
                                             addon=lambda: True, probe=lambda: True))
    assert result.kind == "blocked"
    assert "no-such.example" in result.message and "open the page" in result.message
    assert popen.calls == []
    assert not (tmp_path / "config" / "uivision").exists()          # blocked before provision
    assert any(lvl == "warn" and "no OPEN tab matches" in msg for _s, msg, lvl in rows)


async def test_titleless_url_match_runs_by_index(tmp_path, frozen_time):
    """A matched tab without a title still runs — the tab=N index needs no title."""
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    deliver = FakeDeliver()
    rows, report = reports()
    window = {"index": 1, "active": {"url": "https://arena.ai/image/titled", "title": "Titled"},
              "tabs": [{"url": "https://arena.ai/image/blank", "title": ""},
                       {"url": "https://arena.ai/image/titled", "title": "Titled"}]}
    sessions = [{"name": "Work", "dir": "/ff/p1", "rows": list(window["tabs"]),
                 "windows": [window], "source": "", "stamp": 1.0}]
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai/image/"),
                            report, RunSeams(sleep=noop_sleep, popen=FakePopen(),
                                             profiles=lambda: sessions,
                                             addon=lambda: True, probe=lambda: True,
                                             os_windows=lambda: [(11, "Titled — Mozilla Firefox")],
                                             deliver=deliver))
    assert result.kind == "ok"
    assert len(deliver.calls) == 1                        # the blank tab runs by index
    assert parse_qs(urlsplit(deliver.calls[0][1]).query)["cmd_var3"] == ["tab=-2"]
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "2 tab(s) match — the run addresses the first" in text


# ── profile selection + skip_no_match (2026-09-24) ───────────────────────────

async def test_profile_filter_keeps_only_selected_profiles(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    popen = FakePopen()
    rows, report = reports()
    sessions = [
        {"name": "Alpha", "dir": "/ff/a", "rows": [
            {"url": "https://arena.ai/1", "title": "Arena A"}],
         "windows": [], "source": "", "stamp": 1.0},
        {"name": "Beta", "dir": "/ff/b", "rows": [
            {"url": "https://arena.ai/2", "title": "Arena B"}],
         "windows": [], "source": "", "stamp": 1.0},
    ]
    spec = make_spec(tmp_path, pattern="Arena",
                     selected_profiles=("/ff/a",))
    result = await run_test(spec, report, RunSeams(
        sleep=noop_sleep, popen=popen, profiles=lambda: sessions,
        addon=lambda: True, probe=lambda: True, os_windows=lambda: []))
    assert result.kind == "ok"
    assert len(popen.calls) == 1                          # only Alpha's tab runs
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "profile filter: 1 tab(s) dropped" in text


async def test_skip_no_match_blocks_when_all_profiles_have_no_tab(tmp_path, frozen_time):
    rows, report = reports()
    sessions = [
        {"name": "Alpha", "dir": "/ff/a", "rows": [
            {"url": "https://other.example", "title": "Other"}],
         "windows": [], "source": "", "stamp": 1.0},
    ]
    spec = make_spec(tmp_path, pattern="Arena",
                     selected_profiles=("/ff/a",), skip_no_match=True)
    result = await run_test(spec, report, RunSeams(
        profiles=lambda: sessions, addon=lambda: True, probe=lambda: True))
    assert result.kind == "blocked"
    assert "all selected profiles skipped" in result.message
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "no matching tab — skipped" in text


async def test_skip_no_match_warns_per_profile_when_off(tmp_path, frozen_time, monkeypatch):
    rows, report = reports()
    sessions = [
        {"name": "Alpha", "dir": "/ff/a", "rows": [
            {"url": "https://other.example", "title": "Other"}],
         "windows": [], "source": "", "stamp": 1.0},
    ]
    # Fast-forward the clock so the 10s wait expires after one sleep call
    clock = [1_000_000.0]
    monkeypatch.setattr(runner.time, "time", lambda: clock[0])

    async def fast_sleep(sec):
        clock[0] += sec + 1            # each sleep jumps past the deadline

    spec = make_spec(tmp_path, pattern="Arena",
                     selected_profiles=("/ff/a",), skip_no_match=False,
                     wait_timeout_sec=10)
    result = await run_test(spec, report, RunSeams(
        sleep=fast_sleep,
        profiles=lambda: sessions, addon=lambda: True, probe=lambda: True))
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "waiting up to 10s" in text
    assert "no matching tab after 10s — skipped" in text


async def test_wait_for_tab_finds_it_during_the_poll(tmp_path, frozen_time, monkeypatch):
    """skip_no_match OFF + user opens the tab during the wait → it runs."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    popen = FakePopen()
    rows, report = reports()
    empty = [{"name": "Alpha", "dir": "/ff/a", "rows": [
        {"url": "https://other.example", "title": "Other"}],
        "windows": [], "source": "", "stamp": 1.0}]
    full = [{"name": "Alpha", "dir": "/ff/a", "rows": [
        {"url": "https://arena.ai/image/1", "title": "Arena"}],
        "windows": [], "source": "", "stamp": 1.0}]
    calls = [0]

    def profile_source():
        calls[0] += 1
        return full if calls[0] >= 3 else empty

    clock = [1_000_000.0]
    monkeypatch.setattr(runner.time, "time", lambda: clock[0])

    async def fast_sleep(sec):
        clock[0] += 1

    spec = make_spec(tmp_path, pattern="Arena",
                     selected_profiles=("/ff/a",), skip_no_match=False,
                     wait_timeout_sec=30)
    result = await run_test(spec, report, RunSeams(
        sleep=fast_sleep, popen=popen,
        profiles=profile_source, addon=lambda: True, probe=lambda: True,
        os_windows=lambda: []))
    assert result.kind == "ok"
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "matching tab(s) appeared" in text

# ── rescan / retry / skipped / delivery (2026-09-24: first-run rebuild) ──────

async def test_rescan_finds_a_tab_opened_during_the_wait(tmp_path, frozen_time, monkeypatch):
    """Empty session + patterns set: the 20s rescan finds the just-opened tab."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    popen = FakePopen()
    rows, report = reports()
    clock = [1_000_000.0]
    monkeypatch.setattr(runner.time, "time", lambda: clock[0])

    async def fast_sleep(sec):
        clock[0] += 1

    opened = [{"name": "Work", "dir": "/ff/p1", "rows": [
        {"url": "https://arena.ai", "title": "Agent Arena"}],
        "windows": [], "source": "", "stamp": 1.0}]
    t0 = clock[0]

    def late_profiles():
        # the user opens the tab 3s into the wait — the rescan's reload sees it
        return opened if clock[0] >= t0 + 3 else []

    spec = make_spec(tmp_path)                             # title pattern "Arena"
    result = await run_test(spec, report, RunSeams(
        sleep=fast_sleep, popen=popen, profiles=late_profiles,
        addon=lambda: True, probe=lambda: True, os_windows=lambda: []))
    assert result.kind == "ok"
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "no match — waiting up to 20s for Firefox to flush its session store" in text
    assert "the flush brought 1 matching tab(s)" in text
    assert "addressing title=*Arena*" in text


async def test_rescan_gives_up_and_blocks_with_the_url_pattern(
        tmp_path, frozen_time, monkeypatch):
    """URL-only search + tab never opens within 20s → blocked, naming the URL."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\\n")
    popen = FakePopen()
    rows, report = reports()
    clock = [1_000_000.0]
    monkeypatch.setattr(runner.time, "time", lambda: clock[0])

    async def fast_sleep(sec):
        clock[0] += 1

    spec = make_spec(tmp_path, pattern="", url_pattern="no-such.example")
    result = await run_test(spec, report, RunSeams(
        sleep=fast_sleep, popen=popen, profiles=lambda: [],
        addon=lambda: True, probe=lambda: True))
    assert result.kind == "blocked"
    assert "no-such.example" in result.message
    assert "open the page" in result.message
    assert popen.calls == []
    assert not (tmp_path / "config" / "uivision").exists()   # blocked before provision
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "no match — waiting up to 20s for Firefox to flush its session store" in text
    assert "still no match after the flush wait" in text
    assert any(lvl == "warn" and "still no match after the flush wait" in msg
               for _s, msg, lvl in rows)


async def test_rescan_budget_zero_skips_the_wait_and_blocks(
        tmp_path, frozen_time, no_rescan_wait):
    """Budget 0: the rescan skips the wait entirely and blocks immediately."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\\n")
    calls = [0]

    async def never_sleep(_sec):
        calls[0] += 1
        raise AssertionError("budget 0 must never sleep")  # _safe_sleep would swallow this

    rows, report = reports()
    spec = make_spec(tmp_path, pattern="", url_pattern="no-such.example")
    result = await run_test(spec, report, RunSeams(
        sleep=never_sleep, popen=FakePopen(), profiles=lambda: [],
        addon=lambda: True, probe=lambda: True))
    assert result.kind == "blocked"
    assert "matched no open tab" in result.message
    assert calls == [0]                                # …not a second was ever slept
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "waiting up to 0s for Firefox to flush its session store" in text


async def test_session_snapshot_overrules_selected_profiles(tmp_path, frozen_time):
    """skip_no_match ON + a selection the store never held → all-skipped."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    rows, report = reports()
    sessions = [
        {"name": "Alpha", "dir": "/ff/a", "rows": [
            {"url": "https://other.example", "title": "Other"}],
         "windows": [], "source": "", "stamp": 1.0},
    ]
    spec = make_spec(tmp_path, pattern="Arena",
                     selected_profiles=("/ff/b",), skip_no_match=True)
    result = await run_test(spec, report, RunSeams(
        profiles=lambda: sessions, addon=lambda: True, probe=lambda: True))
    assert result.kind == "blocked"
    assert "all selected profiles skipped" in result.message
    rows_text = " | ".join(m for _s, m, _l in rows)
    # the selection names a profile the store never held — the all-skipped fallback
    assert "every selected profile had no matching tab — all skipped" in rows_text


async def test_locator_retry_drops_the_stale_log_and_retries_fresh(tmp_path, frozen_time):
    """Stale savelog (tab moved) → one retry on a fresh index, then timeout."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    log = tmp_path / "config" / "uivision" / "logs" / f"run-{STAMP}.txt"
    log.parent.mkdir(parents=True)
    log.write_bytes(("Status=Error: failed to find the tab with locator "
                     "tab=-14 ###\n").encode())            # a stale index echoes
    rows, report = reports()
    popen = FakePopen()
    spec = make_spec(tmp_path, pattern="", url_pattern="image",
                     timeout_sec=0)                        # no waiting — the stale log answers
    result = await run_test(spec, report, RunSeams(
        sleep=noop_sleep, popen=popen, profiles=lambda: URL_ONLY,
        addon=lambda: True, probe=lambda: True, os_windows=lambda: []))
    assert result.kind == "timeout"                    # nothing re-answered either log
    assert result.message.startswith("0/2 run(s) ok — ")
    assert popen.calls == []         # manual path: two cold profiles never auto-launch
    assert not log.exists()                            # the stale savelog was dropped
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "2 profiles match" in text                  # the manual reason
    assert "tab not found — retrying once with a fresh resolve" in text
    assert text.count("addressing tab=") == 3          # every attempt re-resolved fresh


async def test_vanished_tab_warns_but_keeps_the_verdict(tmp_path, frozen_time):
    """A tab closed mid-run: the guard warns, the run's own verdict stands."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\\n")
    write_logs(tmp_path, [f"run-{STAMP}.txt"])
    full = [{"name": "Work", "dir": "/ff/p1", "rows": [
        {"url": "https://arena.ai/a", "title": "Arena A"},
        {"url": "https://other.example", "title": "Other"}],
        "windows": [], "source": "", "stamp": 1.0}]
    reduced = [{"name": "Work", "dir": "/ff/p1", "rows": [
        {"url": "https://other.example", "title": "Other"}],
        "windows": [], "source": "", "stamp": 1.0}]
    calls = [0]

    def closing_profiles():
        # detect + the guard snapshot see everything; the post-run verify sees one less
        calls[0] += 1
        return full if calls[0] <= 2 else reduced

    rows, report = reports()
    result = await run_test(make_spec(tmp_path, pattern="Arena"), report, RunSeams(
        sleep=noop_sleep, popen=FakePopen(), profiles=closing_profiles,
        addon=lambda: True, probe=lambda: True, os_windows=lambda: []))
    assert result.kind == "ok"                        # the macro itself completed
    assert calls == [3]              # detect, the guard snapshot, the post-run verify
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "are no longer in the session store" in text
    assert "https://arena.ai/a" in text               # the vanished tab is named
    assert any(lvl == "warn" and "no longer in the session store" in msg
               for _s, msg, lvl in rows)


async def test_unresolvable_titleless_run_is_skipped_not_aborted(tmp_path, frozen_time):
    """A URL match with no position info: skipped loudly, never aimed blind."""
    sessions = [{"name": "Stealth", "dir": "/ff/s", "rows": [
        {"url": "https://arena.ai/image/x", "title": ""}],
        "windows": [], "source": "", "stamp": 1.0}]
    rows, report = reports()
    spec = make_spec(tmp_path, pattern="", url_pattern="arena.ai/image/")
    result = await run_test(spec, report, RunSeams(
        profiles=lambda: sessions, addon=lambda: True, probe=lambda: True))
    assert result.kind == "skipped"
    assert result.message == "the tab is no longer open"
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "skipped — the tab is no longer open" in text
    assert any(lvl == "warn" and "skipped" in msg for _s, msg, lvl in rows)


async def test_refused_delivery_degrades_to_manual_and_still_polls(tmp_path, frozen_time):
    """Address-bar keys refused: the manual steps print, the savelog wait still runs."""
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\\n")
    window = {"index": 1, "active": {"url": "https://arena.ai/a", "title": "A1"},
              "tabs": [{"url": "https://arena.ai/a", "title": "A1"}]}
    sessions = [{"name": "Work", "dir": "/ff/p1", "rows": list(window["tabs"]),
                 "windows": [window], "source": "", "stamp": 1.0}]
    deliver = FakeDeliver(refuse=True)            # SendInput fails on the window
    rows, report = reports()
    spec = make_spec(tmp_path, pattern="", url_pattern="arena.ai", timeout_sec=0)
    result = await run_test(spec, report, RunSeams(
        sleep=noop_sleep, popen=FakePopen(), profiles=lambda: sessions,
        addon=lambda: True, probe=lambda: True,
        os_windows=lambda: [(999, "A1 — Mozilla Firefox")], deliver=deliver))
    assert result.kind == "timeout"               # the degraded poll found no savelog
    assert deliver.attempts == 1 and deliver.calls == []   # tried once, never re-aimed
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "address-bar delivery failed (SendInput failed)" in text
    assert "open the URL below by hand instead" in text
    assert "watching the session store" not in text   # refused = patient wait, no receipt theater
    assert "re-sending the keystrokes" not in text
    assert "savelog wait expired" in text             # ...but the timeout gets its autopsy


async def test_delivery_to_the_resolved_window_sends_each_profile_its_tab(
        tmp_path, frozen_time):
    """Two RUNNING windows, same URL: the resolver aims each delivery, not the OS."""
    write_logs(tmp_path, [f"run-{STAMP}.txt", f"run-{STAMP}-2.txt"])
    popen = FakePopen()
    deliver = FakeDeliver()
    rows, report = reports()
    same_url = [
        {"name": "Work", "dir": "/ff/p1", "rows": [
            {"url": "https://arena.ai/shared", "title": "First"}],
         "windows": [{"index": 1, "active": {"url": "https://arena.ai/shared", "title": "First"},
                      "tabs": [{"url": "https://arena.ai/shared", "title": "First"},
                               {"url": "https://other.example", "title": "Other"}]}],
         "source": "", "stamp": 1.0},
        {"name": "", "dir": "/ff/p2", "rows": [
            {"url": "https://arena.ai/shared", "title": ""}],       # titleless second
         "windows": [{"index": 1, "active": {"url": "https://arena.ai/shared", "title": ""},
                      "tabs": [{"url": "https://arena.ai/shared", "title": ""}]}],
         "source": "", "stamp": 1.0},
    ]
    # the OS lists ONLY the first window — mapping would hit it; the resolver aims wider
    seen = [(11, "First — Mozilla Firefox")]
    result = await run_test(make_spec(tmp_path, pattern="", url_pattern="arena.ai/shared"),
                            report, RunSeams(
                                sleep=noop_sleep, popen=popen, profiles=lambda: same_url,
                                addon=lambda: True, probe=lambda: True,
                                os_windows=lambda: seen, deliver=deliver))
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "no Firefox window matches “arena.ai/shared”" in text     # the mapping warned
    # first profile's window IS the mapping — the resolver agrees and delivers there
    assert (11, deliver.calls[0][1]) in deliver.calls
    # second profile: nothing mapped, nothing running its tabs → manual path (no delivery)
    assert len(deliver.calls) == 1
    assert result.kind in ("ok", "error")
