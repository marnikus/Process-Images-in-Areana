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
    await runner_mod.run_test(make_spec(tmp_path, pattern="arena.ai"), report, seams)
    lines = [m for _s, m, _l in rows]
    assert "firefox open tabs seen: 4" in lines
    assert "firefox tab 1: https://arena.ai/page0 — T0" in lines
    assert "firefox tab 4: https://other.example — O" in lines
    assert "pattern “arena.ai” matches 3 open tab(s):" in lines
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
    await run_test(make_spec(tmp_path, pattern="arena.ai"), report, seams)
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "firefox open tabs seen: 1" in text
    assert "firefox tab 1: https://arena.ai/image/direct?model_a=max" in text
    assert "matches 1 open tab(s):" in text
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
    result = await run_test(make_spec(tmp_path, pattern=""), report, seams)
    assert result.kind == "stopped"                    # detect ran, stop honoured after
    text = " | ".join(f"{s}:{m}" for s, m, _l in rows)
    assert "open tabs seen: 0" in text and "no session store readable" in text


def make_spec(tmp_path, **over):
    kw = dict(pattern="Arena", url="https://arena.ai", target="xpath=//a[span[text()='New Chat']]",
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

    # the macro landed on the hard drive, XClick-only, values via cmd vars
    macro_file = tmp_path / "uivhome" / "macros" / "Python_XClick_Demo.json"
    doc = json.loads(macro_file.read_text(encoding="utf-8"))
    assert doc["Name"] == "Python_XClick_Demo"
    assert [c["Command"] for c in doc["Commands"]] == [
        "store", "store", "selectWindow", "if", "selectWindow", "end", "store",
        "bringBrowserToForeground", "pause", "XClick", "echo"]

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


def test_tab_target_reuses_the_pattern_or_opens_fresh():
    assert runner.tab_target("Arena") == "title=*Arena*"
    assert runner.tab_target("  Agent Arena  ") == "title=*Agent Arena*"
    assert runner.tab_target("") == "tab=open"
    assert runner.tab_target("   ") == "tab=open"


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
