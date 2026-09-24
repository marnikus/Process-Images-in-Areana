"""The window's run: every matching tab, in every open profile, one after another.

RULE 8: the production scan (no injected list) must ignore a newer closed
profile and launch only the open one. Injected lists cover the per-tab
verdict, stop, and the refusal to launch when nothing matches.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.browser.uivision import desktop, dispatch, profiles, runner, tabs

pytestmark = pytest.mark.unit

OK_LOG = "Status=OK\n[info] echo: macro finished\n"


def make_spec(tmp_path, **kw):
    binary = tmp_path / "firefox"
    binary.write_text("x", encoding="utf-8")
    values = dict(binary=str(binary), pattern="Arena", macro="Python_XClick_Demo",
                  config_dir=str(tmp_path / "cfg"), storage="xfile", pause_ms=3000,
                  target="Arena", timeout_sec=5, home=str(tmp_path / "uivhome"))
    values.update(kw)
    return runner.RunSpec(**values)


def write_log(argv, text=OK_LOG):
    log = parse_qs(urlsplit(argv[-1]).query)["savelog"][0]
    Path(log).write_text(text, encoding="utf-8")


def recording_popen(launched, text=OK_LOG):
    def popen(argv, **_kw):
        launched.append(list(argv))
        write_log(argv, text)
        return SimpleNamespace(pid=1)
    return popen


def two_open():
    work = {"path": "/p/work", "name": "Work", "label": "Work [abc.default]",
            "source": "recovery.jsonlz4", "lock": "open", "windows": [],
            "rows": [{"url": "https://arena.ai/a", "title": "Arena A"},
                     {"url": "https://arena.ai/b", "title": "Arena B"},
                     {"url": "https://other.example", "title": "Other"}]}
    home = {"path": "/p/home", "name": "Home", "label": "Home [xyz.default]",
            "source": "recovery.jsonlz4", "lock": "open", "windows": [],
            "rows": [{"url": "https://arena.ai/c", "title": "Arena C"}]}
    return [work, home], [Path("/p/closed.default")]


def cmd_var3(argv):
    return parse_qs(urlsplit(argv[-1]).query)["cmd_var3"][0]


async def test_every_open_profile_and_every_distinct_title_is_launched(tmp_path):
    launched = []
    opened, closed = two_open()
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, closed),
                                  addon=lambda: True, probe=lambda: False)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "ok"
    assert [argv[1:3] for argv in launched] == [["-P", "Work"], ["-P", "Work"], ["-P", "Home"]]
    assert [cmd_var3(argv) for argv in launched] == [
        "title=Arena A", "title=Arena B", "title=Arena C"]
    assert all(argv[-1].startswith("file://") for argv in launched)
    assert all("-no-remote" not in argv and "--new-instance" not in argv for argv in launched)
    text = "\n".join(step[1] for step in result.steps)
    assert "firefox profiles open: 2 (Work [abc.default], Home [xyz.default])" in text
    assert "1 closed skipped (closed.default)" in text
    assert "profile Work [abc.default]: 3 tab(s), 2 match" in text
    assert "profile Home [xyz.default]: 1 tab(s), 1 match" in text
    assert "match 1: https://arena.ai/a — Arena A" in text
    assert "profile Work [abc.default] tab 1/3: ok:" in text
    assert "profile Home [xyz.default] tab 3/3: ok:" in text
    assert "3/3 tab(s) ok, 3 matching, across 2 profile(s)" in result.message


async def test_the_same_title_in_two_profiles_runs_in_both(tmp_path):
    launched = []
    opened = [
        {"path": "/p/work", "name": "Work", "label": "Work", "rows": [
            {"url": "https://arena.ai/a", "title": "Arena"}], "windows": []},
        {"path": "/p/home", "name": "Home", "label": "Home", "rows": [
            {"url": "https://arena.ai/b", "title": "Arena"}], "windows": []},
    ]
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, []),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "ok"
    assert [argv[1:3] for argv in launched] == [["-P", "Work"], ["-P", "Home"]]
    assert "2/2 tab(s) ok, 2 matching, across 2 profile(s): Work, Home" in result.message


async def test_a_repeated_title_in_one_profile_is_logged_and_not_double_clicked(tmp_path):
    launched = []
    opened = [{"path": "/p/work", "name": "Work", "label": "Work", "windows": [],
               "rows": [{"url": "https://arena.ai/a", "title": "Arena"},
                        {"url": "https://arena.ai/b", "title": "Arena"}]}]
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, []),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert len(launched) == 1
    assert result.kind == "ok"
    assert "1 skipped" in result.message
    assert any("same title" in step[1] for step in result.steps)


async def test_no_match_and_no_open_profile_launch_nothing(tmp_path):
    launched = []
    quiet = {"path": "/p/work", "name": "Work", "label": "Work", "windows": [],
             "rows": [{"url": "https://other.example", "title": "Other"}]}
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: ([quiet], []), probe=lambda: False)
    missed = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert missed.kind == "blocked" and launched == []
    assert "nothing launched" in missed.message
    none = dispatch.ProfileSeams(popen=recording_popen(launched),
                                 profiles=lambda: ([], [Path("/p/closed")]),
                                 probe=lambda: False)
    empty = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, none)
    assert empty.kind == "blocked" and launched == []
    assert "no open Firefox profile" in empty.message


async def test_a_blank_pattern_blocks_before_any_file_is_written(tmp_path):
    launched = []
    opened, _closed = two_open()
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, []), probe=lambda: False)
    result = await dispatch.run_profiles(make_spec(tmp_path, pattern="  "), lambda *_a: None, seams)
    assert result.kind == "blocked"
    assert launched == []
    assert not (tmp_path / "cfg").exists()


async def test_stop_after_the_first_tab_does_not_launch_the_rest(tmp_path):
    launched = []

    def stop():
        return len(launched) >= 1

    opened, _closed = two_open()
    seams = dispatch.ProfileSeams(popen=recording_popen(launched), stop=stop,
                                  profiles=lambda: (opened, _closed),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert len(launched) == 1
    assert result.kind == "stopped"
    assert "stopped after 1 tab" in result.message


async def test_one_tab_error_does_not_skip_the_next_profile(tmp_path):
    launched = []

    def popen(argv, **_kw):
        launched.append(list(argv))
        text = "Status=Error: click failed\n" if len(launched) == 1 else OK_LOG
        write_log(argv, text)
        return SimpleNamespace(pid=1)

    opened, closed = two_open()
    seams = dispatch.ProfileSeams(popen=popen, profiles=lambda: (opened, closed),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert len(launched) == 3
    assert result.kind == "error"
    assert result.message.startswith("2/3 tab(s) ok")
    assert any("error:" in step[1] for step in result.steps)


async def test_a_silent_log_is_a_timeout_and_the_next_tab_still_runs(tmp_path):
    launched = []

    def popen(argv, **_kw):
        launched.append(list(argv))
        return SimpleNamespace(pid=1)

    opened = [{"path": "/p/work", "name": "Work", "label": "Work", "windows": [],
               "rows": [{"url": "https://arena.ai/a", "title": "Arena A"},
                        {"url": "https://arena.ai/b", "title": "Arena B"}]}]
    seams = dispatch.ProfileSeams(popen=popen, profiles=lambda: (opened, []),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path, timeout_sec=0), lambda *_a: None, seams)
    assert len(launched) == 2
    assert result.kind == "timeout"
    assert "0/2 tab(s) ok" in result.message


async def test_a_refused_launch_is_logged_and_does_not_crash_the_run(tmp_path):
    def popen(_argv, **_kw):
        raise PermissionError("denied")

    opened = [{"path": "/p/work", "name": "Work", "label": "Work", "windows": [],
               "rows": [{"url": "https://arena.ai/a", "title": "Arena"}]}]
    seams = dispatch.ProfileSeams(popen=popen, profiles=lambda: (opened, []),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "blocked"
    assert any("would not start" in step[1] for step in result.steps)


async def test_a_missing_binary_launches_nothing(tmp_path):
    launched = []
    opened, _closed = two_open()
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, []), probe=lambda: False)
    result = await dispatch.run_profiles(
        make_spec(tmp_path, binary=str(tmp_path / "missing-firefox")), lambda *_a: None, seams)
    assert result.kind == "blocked" and launched == []
    assert "not found" in result.message or any("not found" in step[1].lower() or "Firefox" in step[1]
                                                for step in result.steps)


async def test_a_newer_closed_profile_is_not_the_one_that_runs(tmp_path, monkeypatch):
    """The reported bug: the last-written session file is a closed profile."""
    launched = []
    opened = tmp_path / "open.default"
    closed = tmp_path / "closed.default"
    for folder, url, title in (
            (opened, "https://arena.ai/open", "Arena Open"),
            (closed, "https://arena.ai/closed", "Arena Closed")):
        backups = folder / "sessionstore-backups"
        backups.mkdir(parents=True)
        (backups / "recovery.json").write_text(json.dumps({"windows": [{"tabs": [
            {"entries": [{"url": url, "title": title}]}]}]}), encoding="utf-8")
    (opened / "lock").symlink_to(f"127.0.0.1:+{os.getpid()}")
    future = (closed / "sessionstore-backups" / "recovery.json").stat().st_mtime + 500
    os.utime(closed / "sessionstore-backups" / "recovery.json", (future, future))
    monkeypatch.setattr(tabs, "profile_dirs", lambda: [closed, opened])
    monkeypatch.setattr(profiles, "name_table", lambda files=None: {
        opened.resolve(): "Open", closed.resolve(): "ClosedNewer"})
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "ok"
    assert len(launched) == 1
    assert launched[0][1:3] == ["-P", "Open"]
    assert cmd_var3(launched[0]) == "title=Arena Open"
    assert "closed.default" in "\n".join(step[1] for step in result.steps)
    assert "ClosedNewer" not in [argv[2] for argv in launched]


async def test_stop_before_the_run_launches_nothing(tmp_path):
    launched = []
    opened, closed = two_open()
    seams = dispatch.ProfileSeams(stop=lambda: True, popen=recording_popen(launched),
                                  profiles=lambda: (opened, closed), probe=lambda: False)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "stopped" and launched == []
    assert "stopped before the run began" in result.message


async def test_a_profile_that_closes_before_launch_is_not_started(tmp_path, monkeypatch):
    folder = tmp_path / "open.default"
    backups = folder / "sessionstore-backups"
    backups.mkdir(parents=True)
    (backups / "recovery.json").write_text(json.dumps({"windows": [{"tabs": [
        {"entries": [{"url": "https://arena.ai/a", "title": "Arena"}]}]}]}), encoding="utf-8")
    (folder / "lock").symlink_to(f"127.0.0.1:+{os.getpid()}")
    monkeypatch.setattr(tabs, "profile_dirs", lambda: [folder])
    monkeypatch.setattr(profiles, "name_table", lambda files=None: {folder.resolve(): "Open"})
    answers = iter([True, False])
    monkeypatch.setattr(profiles, "_keep", lambda _path: next(answers, False))
    launched = []
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert launched == []
    assert result.kind == "blocked"
    assert any("closed before" in step[1] for step in result.steps)


async def test_a_provision_failure_blocks_before_any_launch(tmp_path, monkeypatch):
    def boom(_spec, _recorder):
        raise OSError("disk full")

    monkeypatch.setattr(runner, "_provision", boom)
    launched = []
    opened, _closed = two_open()
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, []), probe=lambda: False)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "blocked" and launched == []
    assert any("cannot prepare" in step[1] for step in result.steps)


async def test_a_popen_that_returns_nothing_is_a_blocked_tab(tmp_path):
    opened = [{"path": "/p/work", "name": "Work", "label": "Work", "windows": [],
               "rows": [{"url": "https://arena.ai/a", "title": "Arena"}]}]
    seams = dispatch.ProfileSeams(popen=lambda *_a, **_k: None,
                                  profiles=lambda: (opened, []), probe=lambda: False)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "blocked"
    assert any("did not start" in step[1] for step in result.steps)


async def test_an_untitled_tab_falls_back_to_the_pattern_and_says_so(tmp_path):
    launched = []
    opened = [{"path": "/p/work", "name": "", "label": "work", "windows": [], "lock": "unknown",
               "rows": [{"url": "https://arena.ai/a", "title": ""}]}]
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, [Path(f"/c/{i}") for i in range(8)]),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "ok"
    assert launched[0][1:3] == ["--profile", "/p/work"]
    assert cmd_var3(launched[0]) == "title=*Arena*"
    text = "\n".join(step[1] for step in result.steps)
    assert "no title" in text and "lock check failed" in text and "+2" in text


async def test_a_long_match_list_is_truncated_in_the_log(tmp_path):
    launched = []
    rows = [{"url": f"https://arena.ai/{i}", "title": f"Arena {i}"} for i in range(22)]
    opened = [{"path": "/p/work", "name": "Work", "label": "Work", "windows": [], "rows": rows}]
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, []), probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert len(launched) == 22 and result.kind == "ok"
    assert any("+2 more matching" in step[1] for step in result.steps)


async def test_a_window_we_cannot_raise_does_not_stop_the_launch(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("display gone")

    monkeypatch.setattr(desktop, "foreground_tab_window", boom)
    launched = []
    opened, _closed = two_open()
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, []), probe=lambda: False)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert result.kind == "ok" and len(launched) == 3
    assert any("could not raise" in step[1] for step in result.steps)


async def test_a_mapped_window_and_a_foreground_hit_are_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "foreground_tab_window", lambda *_a, **_k: True)
    launched = []
    opened = [{"path": "/p/work", "name": "Work", "label": "Work", "windows": [{"tabs": []}],
               "rows": [{"url": "https://arena.ai/a", "title": "Arena"}]}]
    seams = dispatch.ProfileSeams(popen=recording_popen(launched),
                                  profiles=lambda: (opened, []), probe=lambda: False)
    mapped = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert any("window on top" in step[1] for step in mapped.steps)
    monkeypatch.setattr(desktop, "foreground_tab_window", lambda *_a, **_k: False)
    monkeypatch.setattr(desktop, "foreground", lambda _pattern: (["win"], 1))
    hit = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert any("1/1 window" in step[1] for step in hit.steps)


async def test_a_corrupt_savelog_is_an_error_and_the_next_tab_still_runs(tmp_path):
    launched = []

    def popen(argv, **_kw):
        launched.append(list(argv))
        write_log(argv, "this is not a status line\n" if len(launched) == 1 else OK_LOG)
        return SimpleNamespace(pid=1)

    opened, closed = two_open()
    seams = dispatch.ProfileSeams(popen=popen, profiles=lambda: (opened, closed),
                                  probe=lambda: False, addon=lambda: True)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert len(launched) == 3
    assert result.kind == "error"


async def test_stop_after_the_window_raise_does_not_launch(tmp_path):
    launched = []
    calls = iter(range(10))

    def stop():
        return next(calls) >= 2

    opened = [{"path": "/p/work", "name": "Work", "label": "Work", "windows": [],
               "rows": [{"url": "https://arena.ai/a", "title": "Arena"}]}]
    seams = dispatch.ProfileSeams(stop=stop, popen=recording_popen(launched),
                                  profiles=lambda: (opened, []), probe=lambda: False)
    result = await dispatch.run_profiles(make_spec(tmp_path), lambda *_a: None, seams)
    assert launched == []
    assert result.kind == "stopped"
    assert "stopped after 0 tab" in result.message
