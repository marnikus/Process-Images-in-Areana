"""Ui.Vision runner — the full app-driven flow, spawn + sleep faked (RULE 8).

RED: `app.browser.uivision_runner` did not exist; provisioning (selectWindow
first), the pre-flight gate and the savelog wait lived in an untested external
script. The fakes stand in for the process boundary only — the provision →
gate → spawn → wait logic under test is the real code.
"""

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from app.browser import uivision_runner as ur

pytestmark = pytest.mark.unit


def _run(tmp_path, **over):
    args = {"home": str(tmp_path / "uv"), "page_path": str(tmp_path / "u v" / "ui.vision.html"),
            "macro": "Python_XClick_Demo", "pattern": "Arena",
            "commands": [{"Command": "XClick", "Target": "img.png", "Value": ""}],
            "firefox_exe": "firefox", "savelog": str(tmp_path / "my logs" / "run 1.txt")}
    args.update(over)
    return ur.UivisionRun(**args)


class _Spawn:
    """Fake Firefox: records argv, optionally fails like a missing binary."""

    def __init__(self, fail=None):
        self.argv = None
        self.fail = fail
        self.pid = 4242

    def __call__(self, argv):
        self.argv = argv
        if self.fail is not None:
            raise self.fail
        return self


class _Clock:
    """Fake sleep: instant, writes the savelog on the 2nd tick to prove polling."""

    def __init__(self, savelog, status=None):
        self.ticks = 0
        self.savelog = savelog
        self.status = status

    def __call__(self, seconds):
        self.ticks += 1
        if self.ticks == 2 and self.status is not None:
            Path(self.savelog).write_text(self.status + "\nmore log...\n", encoding="utf-8")


def _hooks(spawn, clock):
    reports = []
    hooks = ur.RunHooks(spawn=spawn, sleep=clock,
                        report=lambda m, level="info": reports.append((level, m)))
    return hooks, reports


def test_success_provisions_select_window_first_and_spawns_encoded_url(tmp_path):
    run = _run(tmp_path)
    spawn, clock = _Spawn(), _Clock(run.savelog, "Status=OK, runtime 12s")
    hooks, reports = _hooks(spawn, clock)
    result = ur.run_macro(run, hooks)
    assert result == {"ok": True, "outcome": "success", "detail": "Status=OK, runtime 12s",
                      "savelog": run.savelog}
    assert clock.ticks == 2, "polled, found nothing, slept, then read the status"
    saved = json.loads(Path(run.home, "macros", "Python_XClick_Demo.json").read_text("utf-8"))
    assert saved["Commands"][0] == {"Command": "selectWindow",
                                    "Target": "title=*Arena*", "Value": ""}
    assert saved["Commands"][1]["Command"] == "XClick"
    assert spawn.argv[0] == "firefox" and spawn.argv[1].startswith("file:///")
    assert " " not in spawn.argv[1] and "%20" in spawn.argv[1]
    assert "tab=" not in spawn.argv[1], "tab= cannot be sent anymore"
    back = dict(parse_qsl(urlsplit(spawn.argv[1]).query))
    assert back["macro"] == "Python_XClick_Demo" and back["savelog"] == run.savelog
    assert any("provision: macro written" in m for _, m in reports)


def test_macro_error_reports_first_status_line(tmp_path):
    run = _run(tmp_path)
    spawn, clock = _Spawn(), _Clock(run.savelog, "[error] Can't find macro with name \"X\"")
    hooks, reports = _hooks(spawn, clock)
    result = ur.run_macro(run, hooks)
    assert result["ok"] is False and result["outcome"] == "macro-error"
    assert "Can't find macro" in result["detail"]
    assert any(lv == "error" and "macro error" in m for lv, m in reports)


def test_spawn_failure_is_refused_not_timeout(tmp_path):
    run = _run(tmp_path)
    spawn = _Spawn(fail=OSError(2, "The system cannot find the file specified"))
    hooks, _ = _hooks(spawn, _Clock(run.savelog))
    result = ur.run_macro(run, hooks)
    assert result["ok"] is False and result["outcome"] == "refused"
    assert "cannot start firefox" in result["detail"]


def test_timeout_when_savelog_never_appears(tmp_path):
    run = _run(tmp_path, timeout_sec=3, poll_sec=1)
    spawn, clock = _Spawn(), _Clock(run.savelog)
    hooks, _ = _hooks(spawn, clock)
    result = ur.run_macro(run, hooks)
    assert result == {"ok": False, "outcome": "timeout",
                      "detail": f"no status line in {run.savelog} within 3s"
                                " — check the extension ran the macro",
                      "savelog": run.savelog}
    assert spawn.argv is not None and clock.ticks == 3


def test_unwritable_home_is_refused_before_spawn(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a dir", encoding="utf-8")
    run = _run(tmp_path, home=str(blocker))
    spawn, clock = _Spawn(), _Clock(run.savelog)
    result = ur.run_macro(run, _hooks(spawn, clock)[0])
    assert result["ok"] is False and result["outcome"] == "refused"
    assert "cannot write macro" in result["detail"] and spawn.argv is None


def test_blank_savelog_defaults_under_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = _run(tmp_path, savelog="", timeout_sec=1, poll_sec=1)
    spawn = _Spawn()
    result = ur.run_macro(run, _hooks(spawn, _Clock(""))[0])
    assert result["outcome"] == "timeout", "nothing writes it; the default must still parse"
    assert result["savelog"].startswith(str(tmp_path / "uivision-logs"))
    assert (tmp_path / "uivision-logs").is_dir(), "launch gate created the dir"
    assert "Python_XClick_Demo" in dict(parse_qsl(urlsplit(spawn.argv[1]).query))["savelog"]


def test_default_savelog_path_shape():
    path = ur.default_savelog_path("Python_XClick_Demo")
    assert path.endswith(".txt") and "uivision-logs" in path
    assert "Python_XClick_Demo" in path
    assert "macro-" in ur.default_savelog_path("!!!")
