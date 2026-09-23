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
    result = await run_test(make_spec(tmp_path), report,
                            RunSeams(sleep=noop_sleep, popen=popen))

    assert result.kind == "ok" and "macro completed" in result.message
    assert result.lines == ("echo: done — XClick fired (native OS input)",)
    assert [step for step, _msg in result.steps] == [
        "provision", "provision", "foreground", "launch", "launch", "result"]

    # the macro landed on the hard drive, XClick-only, values via cmd vars
    macro_file = tmp_path / "uivhome" / "macros" / "Python_XClick_Demo.json"
    doc = json.loads(macro_file.read_text(encoding="utf-8"))
    assert doc["Name"] == "Python_XClick_Demo"
    assert [c["Command"] for c in doc["Commands"]] == [
        "open", "bringBrowserToForeground", "pause", "XClick", "echo"]

    # the launch line: exactly [binary, autorun-url] with the official params
    assert len(popen.calls) == 1
    argv = popen.calls[0]
    assert argv[0] == str(binary) and len(argv) == 2
    url = argv[1]
    assert url.startswith("file://") and "ui.vision.html?" in url
    for param in ("macro=Python_XClick_Demo", "storage=xfile", "direct=1",
                  "savelog=", "cmd_var1=", "cmd_var2=", "closeRPA=1"):
        assert param in url, param

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
    assert result.steps == ()
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


async def test_timeout_when_the_savelog_never_answers(tmp_path, frozen_time):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")
    result = await run_test(make_spec(tmp_path, timeout_sec=0), lambda *_a: None,
                            RunSeams(sleep=noop_sleep, popen=FakePopen()))
    assert result.kind == "timeout"
    assert "deadline" in result.message
