"""Profile liveness — the lockfile witness (open profiles only).

RULE 8: real lockfiles in tmp dirs (a held `parent.lock`, a `lock` symlink to
a PID); the Windows sharing check rides an injected opener, the POSIX PID
check a monkeypatched `os.kill` — no Firefox anywhere.
"""

import os
from pathlib import Path

import pytest

from app.browser.uivision import locks

pytestmark = pytest.mark.unit


def _live_lock(profile: Path) -> Path:
    link = profile / "lock"
    link.symlink_to(f"127.0.0.1:+{os.getpid()}")
    return link


def test_windows_running_needs_a_held_lock(tmp_path):
    assert locks._windows_running(tmp_path) is False              # no parent.lock
    (tmp_path / "parent.lock").write_text("stale")
    assert locks._windows_running(tmp_path, opener=lambda p: None) is False  # openable = stale

    def _held(path):
        raise PermissionError("sharing violation")

    assert locks._windows_running(tmp_path, opener=_held) is True
    calls = []
    assert locks._windows_running(tmp_path / "gone", opener=calls.append) is False
    assert calls == []                                             # missing: opener never runs


def test_try_open_roundtrips_a_plain_file(tmp_path):
    target = tmp_path / "parent.lock"
    target.write_text("x")
    assert locks._try_open(target) is None


def test_lock_pid_parses_or_refuses():
    assert locks._lock_pid("127.0.0.1:+1234") == 1234
    assert locks._lock_pid("no-plus-here") is None
    assert locks._lock_pid("") is None
    assert locks._lock_pid(None) is None
    assert locks._lock_pid("+abc") is None


def test_posix_running_needs_a_live_pid(tmp_path):
    assert locks._posix_running(tmp_path) is False                # no lock at all
    _live_lock(tmp_path)
    assert locks._posix_running(tmp_path) is True                 # own pid answers
    (tmp_path / "lock").unlink()
    (tmp_path / "parent.lock").symlink_to(f"127.0.0.1:+{os.getpid()}")
    assert locks._posix_running(tmp_path) is True                 # parent.lock fallback


def test_posix_running_rejects_stale_and_malformed(tmp_path, monkeypatch):
    (tmp_path / "lock").symlink_to("127.0.0.1:+999999999")
    monkeypatch.setattr(os, "kill", lambda pid, sig: (_ for _ in ()).throw(
        ProcessLookupError()))
    assert locks._posix_running(tmp_path) is False                # the crash left it behind


def test_posix_running_malformed_lock_is_closed(tmp_path):
    (tmp_path / "lock").symlink_to("not-a-pid")
    assert locks._posix_running(tmp_path) is False


def test_posix_running_unowned_live_pid_is_open(tmp_path, monkeypatch):
    (tmp_path / "lock").symlink_to("127.0.0.1:+1234")
    monkeypatch.setattr(os, "kill", lambda pid, sig: (_ for _ in ()).throw(
        PermissionError()))
    assert locks._posix_running(tmp_path) is True                 # alive, another user's


def test_is_running_dispatches_by_platform(monkeypatch):
    monkeypatch.setattr(locks, "_windows_running", lambda d, opener=None: "W")
    monkeypatch.setattr(locks, "_posix_running", lambda d: "P")
    monkeypatch.setattr(locks.sys, "platform", "win32")
    assert locks.is_running("/x") == "W"
    monkeypatch.setattr(locks.sys, "platform", "linux")
    assert locks.is_running("/x") == "P"


def test_is_running_never_raises():
    assert locks.is_running(None) is False
    assert locks.is_running(12345) is False


def test_running_and_closed_partition(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    _live_lock(live)
    shut = tmp_path / "shut"
    shut.mkdir()
    assert locks.running([live, shut]) == [live]
    assert locks.closed([live, shut]) == [shut]
    assert locks.running([]) == [] and locks.closed(None) == []
