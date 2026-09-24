"""Open-profile scan: every running Firefox, never the freshest file alone.

RULE 8: real profile dirs, real lock symlinks, real profiles.ini text. A
closed profile with a newer session file must not hide an older open one —
that was the bug.
"""

import json
import os
from pathlib import Path

import pytest

from app.browser.uivision import profile_lock, profiles

pytestmark = pytest.mark.unit

STORE = {"windows": [{"tabs": [
    {"entries": [{"url": "https://arena.ai/a", "title": "Arena A"}]},
    {"entries": [{"url": "https://other.example", "title": "Other"}]},
]}]}


def write_profile(folder: Path, store=STORE, lock_pid=None) -> Path:
    backups = folder / "sessionstore-backups"
    backups.mkdir(parents=True)
    (backups / "recovery.json").write_text(json.dumps(store), encoding="utf-8")
    if lock_pid:
        (folder / "lock").symlink_to(f"127.0.0.1:+{lock_pid}")
    return folder


def test_pid_from_lock_reads_the_firefox_symlink_form():
    assert profile_lock.pid_from_lock("10.0.0.8:+4242") == 4242
    assert profile_lock.pid_from_lock("hostname:+7") == 7
    assert profile_lock.pid_from_lock("") == 0
    assert profile_lock.pid_from_lock("no-plus") == 0
    assert profile_lock.pid_from_lock("ip:+nope") == 0


def test_pid_alive_knows_this_process_and_a_dead_one():
    assert profile_lock.pid_alive(os.getpid()) is True
    assert profile_lock.pid_alive(0) is False
    assert profile_lock.pid_alive(-3) is False
    assert profile_lock.pid_alive(99_999_999) is False


def test_a_live_lock_symlink_means_the_profile_is_open(tmp_path):
    folder = write_profile(tmp_path / "open", lock_pid=os.getpid())
    assert profile_lock.symlink_pid(folder) == os.getpid()
    assert profile_lock.profile_is_open(folder) is True
    assert profile_lock.safely_open(folder) == "open"


def test_a_dead_lock_and_no_file_lock_means_closed(tmp_path):
    folder = write_profile(tmp_path / "stale", lock_pid=99_999_999)
    assert profile_lock.profile_is_open(folder) is False
    assert profile_lock.safely_open(folder) == "closed"


def test_a_missing_profile_is_closed_not_an_exception(tmp_path):
    assert profile_lock.profile_is_open(tmp_path / "gone") is False
    assert profile_lock.safely_open(tmp_path / "gone") == "closed"


def test_rename_locked_is_the_windows_sharing_violation():
    assert profile_lock.rename_locked(lambda: None) is False

    def refused():
        raise PermissionError("sharing violation")

    assert profile_lock.rename_locked(refused) is True


def test_file_lock_held_uses_rename_when_asked_for_windows(tmp_path, monkeypatch):
    path = tmp_path / "parent.lock"
    path.write_text("held", encoding="utf-8")
    monkeypatch.setattr(profile_lock.os, "rename",
                        lambda *_a: (_ for _ in ()).throw(PermissionError("held")))
    assert profile_lock.file_lock_held(path, windows=True) is True
    monkeypatch.setattr(profile_lock.os, "rename", lambda *_a: None)
    assert profile_lock.file_lock_held(path, windows=True) is False
    assert profile_lock.file_lock_held(tmp_path / "missing", windows=True) is False


def test_fcntl_locked_treats_a_refusal_as_held_and_a_free_file_as_closed(tmp_path):
    path = tmp_path / ".parentlock"
    path.write_text("x", encoding="utf-8")

    def refuse(_path):
        raise OSError("held")

    assert profile_lock.fcntl_locked(path, lock=refuse) is True
    assert profile_lock.fcntl_locked(path, lock=lambda _p: False) is False
    assert profile_lock.fcntl_locked(tmp_path / "missing") is False
    assert profile_lock.fcntl_locked(path) is False  # this process can lock a free file


def test_a_held_parent_lock_means_open_even_without_a_symlink(tmp_path, monkeypatch):
    folder = write_profile(tmp_path / "locked")
    (folder / "parent.lock").write_text("x", encoding="utf-8")
    monkeypatch.setattr(profile_lock, "file_lock_held",
                        lambda path, windows=None: path.name == "parent.lock")
    assert profile_lock.profile_is_open(folder) is True


def test_probe_failure_is_unknown_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_lock, "profile_is_open",
                        lambda _p: (_ for _ in ()).throw(RuntimeError("boom")))
    assert profile_lock.safely_open(tmp_path) == "unknown"


def test_names_in_reads_the_ini_name_not_the_folder(tmp_path):
    work = tmp_path / "Profiles" / "abc.default-release"
    work.mkdir(parents=True)
    text = "\n".join([
        "[Profile0]",
        "Name=Work",
        "IsRelative=1",
        "Path=Profiles/abc.default-release",
        "",
        "[Install1]",
        "Default=Profiles/abc.default-release",
        "",
        "[Profile1]",
        "Name=Missing",
        "IsRelative=1",
        "Path=Profiles/gone",
    ])
    table = profiles.names_in(text, tmp_path)
    assert table == {work.resolve(): "Work"}
    assert profiles.profile_label("Work", "abc.default-release") == "Work [abc.default-release]"
    assert profiles.profile_label("", "abc.default-release") == "abc.default-release"


def test_names_in_is_silent_on_junk():
    assert profiles.names_in("this is not an ini [[[", Path("/tmp")) == {}
    assert profiles.names_in("", Path("/tmp")) == {}


def test_name_table_reads_the_ini_files_the_roots_name(tmp_path, monkeypatch):
    work = tmp_path / "Profiles" / "abc.default"
    work.mkdir(parents=True)
    ini = tmp_path / "profiles.ini"
    ini.write_text("[Profile0]\nName=Work\nIsRelative=1\nPath=Profiles/abc.default\n", encoding="utf-8")
    monkeypatch.setattr(profiles.tabs, "_ini_candidates", lambda _roots: [ini])
    assert profiles.name_table() == {work.resolve(): "Work"}


def test_names_in_accepts_an_absolute_path(tmp_path):
    work = tmp_path / "abs"
    work.mkdir()
    text = f"[Profile0]\nName=Abs\nIsRelative=0\nPath={work}\n"
    assert profiles.names_in(text, tmp_path / "unused") == {work.resolve(): "Abs"}


def test_an_open_profile_with_no_session_is_still_listed(tmp_path):
    folder = tmp_path / "empty.default"
    folder.mkdir()
    (folder / "lock").symlink_to(f"127.0.0.1:+{os.getpid()}")
    opened, closed = profiles.scan_open(dirs=[folder], names={})
    assert closed == []
    assert opened[0]["rows"] == [] and opened[0]["source"] == ""
    assert opened[0]["label"] == "empty.default"


def test_name_table_skips_an_unreadable_ini(tmp_path):
    missing = tmp_path / "no-such.ini"
    assert profiles.name_table(files=[missing]) == {}


def test_scan_open_keeps_every_open_profile_and_skips_a_newer_closed_one(tmp_path):
    older = write_profile(tmp_path / "old.open", lock_pid=os.getpid())
    newer = write_profile(tmp_path / "new.closed")
    future = os.stat(newer / "sessionstore-backups" / "recovery.json").st_mtime + 500
    os.utime(newer / "sessionstore-backups" / "recovery.json", (future, future))
    names = {older.resolve(): "Work", newer.resolve(): "Personal"}
    opened, closed = profiles.scan_open(dirs=[newer, older], names=names)
    assert [item["name"] for item in opened] == ["Work"]
    assert closed == [newer]
    assert opened[0]["label"] == "Work [old.open]"
    assert [row["url"] for row in opened[0]["rows"]] == [
        "https://arena.ai/a", "https://other.example"]
    assert opened[0]["rows"][0]["index"] == 0


def test_two_open_profiles_keep_dir_order_not_mtime_order(tmp_path):
    first = write_profile(tmp_path / "a.default", lock_pid=os.getpid())
    second = write_profile(tmp_path / "b.default", lock_pid=os.getpid(),
                           store={"windows": [{"tabs": [{"entries": [
                               {"url": "https://second.example", "title": "S"}]}]}]})
    future = os.stat(first / "sessionstore-backups" / "recovery.json").st_mtime + 80
    os.utime(second / "sessionstore-backups" / "recovery.json", (future, future))
    opened, closed = profiles.scan_open(dirs=[first, second], names={})
    assert closed == []
    assert [item["folder"] for item in opened] == ["a.default", "b.default"]
    assert opened[1]["rows"][0]["url"] == "https://second.example"


def test_unknown_lock_includes_only_a_fresh_session(tmp_path, monkeypatch):
    fresh = write_profile(tmp_path / "fresh")
    stale = write_profile(tmp_path / "stale")
    old = os.stat(stale / "sessionstore-backups" / "recovery.json").st_mtime - 1000
    os.utime(stale / "sessionstore-backups" / "recovery.json", (old, old))
    monkeypatch.setattr(profile_lock, "profile_is_open",
                        lambda _p: (_ for _ in ()).throw(RuntimeError("probe")))
    opened, closed = profiles.scan_open(dirs=[stale, fresh], names={})
    assert [item["folder"] for item in opened] == ["fresh"]
    assert closed == [stale]
    assert opened[0]["lock"] == "unknown"


def test_tab_matches_url_or_title_and_blank_matches_nothing():
    row = {"url": "https://arena.ai/x", "title": "Chat"}
    assert profiles.tab_matches(row, "Arena") is True
    assert profiles.tab_matches(row, "chat") is True
    assert profiles.tab_matches(row, "missing") is False
    assert profiles.tab_matches(row, "  ") is False
    assert profiles.tab_matches({}, "Arena") is False
    assert profiles.select_target({"title": "Arena Chat"}, "Arena") == "title=Arena Chat"
    assert profiles.select_target({"title": ""}, "Arena") == "title=*Arena*"
    assert profiles.select_target({}, "  ") == ""


def test_matching_jobs_skips_a_repeated_title_but_not_the_same_title_elsewhere():
    work = {"path": "/w", "name": "Work", "label": "Work", "rows": [
        {"url": "https://arena.ai/a", "title": "Arena"},
        {"url": "https://arena.ai/b", "title": "Arena"},
        {"url": "https://other.example", "title": "Other"},
    ]}
    home = {"path": "/h", "name": "Home", "label": "Home", "rows": [
        {"url": "https://arena.ai/c", "title": "Arena"},
    ]}
    jobs = profiles.matching_jobs([work, home], "arena")
    assert [(job["label"], job["url"], job["skipped"]) for job in jobs] == [
        ("Work", "https://arena.ai/a", False),
        ("Work", "https://arena.ai/b", True),
        ("Home", "https://arena.ai/c", False),
    ]
    assert jobs[0]["matched"] == 2
    assert jobs[0]["target"] == "title=Arena"


def test_argv_targets_the_named_profile_and_refuses_a_bare_url(tmp_path):
    binary = tmp_path / "firefox"
    binary.write_text("x", encoding="utf-8")
    url = "file:///tmp/ui.vision.html?macro=Python_XClick_Demo"
    argv = profiles.argv_for(str(binary), url, {"name": "Work", "path": "/p/work"})
    assert argv == [str(binary), "-P", "Work", url]
    by_path = profiles.argv_for(str(binary), url, {"name": "", "path": "/p/work"})
    assert by_path[1:3] == ["--profile", "/p/work"]
    banned_name = profiles.argv_for(str(binary), url, {"name": "selenium", "path": "/p/work"})
    assert banned_name[1:3] == ["--profile", "/p/work"]
    with pytest.raises(ValueError, match="no profile flag"):
        profiles.argv_for(str(binary), url, {"name": "", "path": ""})
    with pytest.raises(ValueError, match="no profile flag"):
        profiles.argv_for(str(binary), url, {"name": "selenium", "path": "/tmp/geckodriver"})
    with pytest.raises(ValueError, match="debugger"):
        profiles.argv_for(str(binary), "file:///tmp/selenium.html", {"name": "Work", "path": "/p"})


def test_a_profile_section_without_a_path_is_skipped(tmp_path):
    assert profiles.names_in("[Profile0]\nName=Nope\n", tmp_path) == {}


def test_names_in_is_silent_when_the_path_will_not_resolve(tmp_path, monkeypatch):
    work = tmp_path / "abs"
    work.mkdir()
    monkeypatch.setattr(Path, "resolve", lambda *_a, **_k: (_ for _ in ()).throw(OSError("loop")))
    text = f"[Profile0]\nName=Abs\nIsRelative=0\nPath={work}\n"
    assert profiles.names_in(text, tmp_path) == {}


def test_a_session_with_no_urls_is_an_empty_profile(tmp_path):
    store = {"windows": [{"tabs": [{"entries": []}, {"entries": [{"title": "no url"}]}]}]}
    folder = write_profile(tmp_path / "blank.default", store=store, lock_pid=os.getpid())
    opened, closed = profiles.scan_open(dirs=[folder], names={})
    assert closed == []
    assert opened[0]["rows"] == []


def test_scan_open_keeps_a_profile_whose_path_will_not_resolve(tmp_path, monkeypatch):
    folder = write_profile(tmp_path / "odd.default", lock_pid=os.getpid())
    real = Path.resolve

    def boom(self, *args, **kwargs):
        if self == folder:
            raise OSError("loop")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", boom)
    opened, _closed = profiles.scan_open(dirs=[folder], names={folder: "Odd"})
    assert opened[0]["name"] == "Odd"
    assert opened[0]["rows"]


def test_file_lock_held_uses_fcntl_when_not_asked_for_windows(tmp_path):
    path = tmp_path / ".parentlock"
    path.write_text("x", encoding="utf-8")
    assert profile_lock.file_lock_held(path) is False
    assert profile_lock.file_lock_held(tmp_path / "missing") is False


def test_argv_for_still_refuses_a_banned_token_that_slipped_the_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "profile_flag", lambda _name, _path: ("-P", "selenium"))
    with pytest.raises(ValueError, match="debugger"):
        profiles.argv_for(str(tmp_path / "firefox"), "file:///tmp/page.html",
                          {"name": "Work", "path": "/p/work"})


def test_a_profile_name_that_looks_like_a_flag_uses_the_path(tmp_path):
    binary = tmp_path / "firefox"
    binary.write_text("x", encoding="utf-8")
    argv = profiles.argv_for(str(binary), "file:///tmp/page.html",
                             {"name": "-Work", "path": "/p/work"})
    assert argv[1:3] == ["--profile", "/p/work"]
