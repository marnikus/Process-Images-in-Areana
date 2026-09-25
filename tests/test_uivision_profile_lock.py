"""The open-profile gate — Firefox's own `lock.ini`, read-only (2026-09-24).

Bug #4's receipt: only a profile whose lock pid is alive is "running". The
pid liveness is checked per OS (posix `kill(pid, 0)`, Windows OpenProcess +
image name) with the OS and the syscall faked here; the reason strings are
pinned because the report lines quote them verbatim.
"""

import ctypes
import os
from pathlib import Path

import pytest

from app.browser.uivision import profile_lock, tabs

pytestmark = pytest.mark.unit


# ── lock.ini parsing ─────────────────────────────────────────────────────────

def write_lock(profile: Path, text: str) -> Path:
    path = profile / profile_lock.LOCK_FILE
    path.write_text(text, encoding="utf-8")
    return path


def test_lock_pid_parses_the_hostname_pid_format(tmp_path):
    write_lock(tmp_path, "myhost.example:1234\n")
    assert profile_lock.lock_pid(tmp_path) == 1234
    write_lock(tmp_path, "host:42")
    assert profile_lock.lock_pid(tmp_path) == 42
    write_lock(tmp_path, "  host : 77  ")
    assert profile_lock.lock_pid(tmp_path) == 77


def test_lock_pid_is_none_when_absent_or_unparseable(tmp_path):
    assert profile_lock.lock_pid(tmp_path) is None
    write_lock(tmp_path, "garbage without colon")
    assert profile_lock.lock_pid(tmp_path) is None
    write_lock(tmp_path, "host:not-a-number")
    assert profile_lock.lock_pid(tmp_path) is None
    write_lock(tmp_path, "host:")
    assert profile_lock.lock_pid(tmp_path) is None
    write_lock(tmp_path, "")
    assert profile_lock.lock_pid(tmp_path) is None


# ── pid liveness: posix ──────────────────────────────────────────────────────

def test_pid_alive_posix_probes_with_kill_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: calls.append((pid, sig)))
    assert profile_lock._pid_alive_posix(1234) is True
    assert calls == [(1234, 0)]


def test_pid_alive_dispatches_to_posix_on_a_posix_host(monkeypatch):
    """The os.name dispatch: on this (posix) host pid_alive takes the kill-zero path."""
    if os.name == "nt":
        pytest.skip("posix dispatch only")
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    assert profile_lock.pid_alive(1234) is True


def test_pid_alive_posix_lookup_error_is_dead(monkeypatch):
    def kill(pid, sig):
        raise ProcessLookupError()
    monkeypatch.setattr(os, "kill", kill)
    assert profile_lock._pid_alive_posix(1234) is False


def test_pid_alive_posix_permission_error_is_alive(monkeypatch):
    """EACCES means the process EXISTS (we just cannot signal it)."""
    def kill(pid, sig):
        raise PermissionError()
    monkeypatch.setattr(os, "kill", kill)
    assert profile_lock._pid_alive_posix(1234) is True


# ── pid liveness: windows ────────────────────────────────────────────────────

class FakeKernel32:
    def __init__(self, handle=1, image_name="firefox.exe", query_ok=True):
        self.handle, self.image_name, self.query_ok = handle, image_name, query_ok
        self.closed = []

    def OpenProcess(self, flags, inherit, pid):
        return self.handle

    def QueryFullProcessImageNameW(self, handle, flags, buf, size_ref):
        if not self.query_ok:
            return 0
        buf.value = self.image_name
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


def test_pid_alive_windows_accepts_a_firefox_owner(monkeypatch):
    kernel = FakeKernel32(image_name="C:\\Program Files\\Mozilla Firefox\\firefox.exe")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", kernel, raising=False)
    assert profile_lock.pid_alive(4242) is True
    assert kernel.closed == [1]                          # the handle is released


def test_pid_alive_windows_rejects_a_reused_pid_of_another_app(monkeypatch):
    kernel = FakeKernel32(image_name="C:\\Windows\\explorer.exe")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", kernel, raising=False)
    assert profile_lock.pid_alive(4242) is False
    assert kernel.closed == [1]


def test_pid_alive_windows_no_handle_is_dead(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", FakeKernel32(handle=0), raising=False)
    assert profile_lock.pid_alive(4242) is False


def test_pid_alive_windows_unreadable_name_is_alive(monkeypatch):
    """The process exists but the name is unreadable — err on the side of running."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", FakeKernel32(query_ok=False), raising=False)
    assert profile_lock.pid_alive(4242) is True


def test_pid_alive_windows_without_windll_is_dead(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delattr(ctypes, "windll", raising=False)
    assert profile_lock.pid_alive(4242) is False


# ── profile_open: the gate + its frozen reasons ──────────────────────────────

def test_profile_open_alive_lock_is_running(tmp_path):
    write_lock(tmp_path, "host:1234")
    assert profile_lock.profile_open(tmp_path, checker=lambda pid: True) == \
        (True, "lock pid 1234 alive")


def test_profile_open_stale_lock_is_not_running(tmp_path):
    write_lock(tmp_path, "host:1234")
    assert profile_lock.profile_open(tmp_path, checker=lambda pid: False) == \
        (False, "stale lock — pid 1234 not running")


def test_profile_open_missing_lock_is_not_running(tmp_path):
    assert profile_lock.profile_open(tmp_path, checker=lambda pid: True) == \
        (False, "no lock file — not running")


# ── the tabs-level open filter ───────────────────────────────────────────────

SESSIONS = [
    {"name": "Work", "dir": "/ff/a", "rows": [{"url": "https://x/1", "title": "T"}],
     "windows": [], "source": "recovery.jsonlz4", "stamp": 1.0},
    {"name": "", "dir": "/ff/b", "rows": [{"url": "https://x/2", "title": "U"}],
     "windows": [], "source": "recovery.jsonlz4", "stamp": 2.0},
]


def test_open_profile_sessions_filters_out_the_closed(monkeypatch):
    monkeypatch.setattr(tabs, "profile_sessions", lambda profiles=None: SESSIONS)

    def fake_open(d, checker=None):
        if d != "/ff/a":
            return (False, "no lock file — not running")
        return ((checker or (lambda pid: True))(777), "")  # /ff/a: alive iff it says

    monkeypatch.setattr(tabs, "profile_open", fake_open)
    open_sessions = tabs.open_profile_sessions()
    assert [s["dir"] for s in open_sessions] == ["/ff/a"]
    # the checker seam rides through to profile_open, once per closed-out candidate
    seen = []
    tabs.open_profile_sessions(checker=lambda pid: (seen.append(pid), True)[1])
    assert seen == [777]


def test_profile_open_states_reports_every_dir_with_its_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(tabs, "profile_dirs", lambda: ["/ff/a", "/ff/b", "/ff/c"])
    monkeypatch.setattr(tabs, "profile_names", lambda: {Path("/ff/a"): "Work"})
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (
        d == "/ff/a", "lock pid 11 alive" if d == "/ff/a" else "no lock file — not running"))
    states = tabs.profile_open_states()
    assert states == [("/ff/a", "Work", True, "lock pid 11 alive"),
                      ("/ff/b", "", False, "no lock file — not running"),
                      ("/ff/c", "", False, "no lock file — not running")]


def test_autorun_tab_seen_finds_the_marker_in_open_profiles_only(tmp_path, monkeypatch):
    seen_sessions = [
        {"name": "Work", "dir": "/ff/a", "rows": [
            {"url": "file:///uivision/ui.vision.html?macro=M", "title": "Ui.Vision"},
            {"url": "https://x/1", "title": "T"}], "windows": [], "source": "", "stamp": 1.0},
        {"name": "Play", "dir": "/ff/b", "rows": [
            {"url": "https://x/2", "title": "U"}], "windows": [], "source": "", "stamp": 2.0},
    ]
    monkeypatch.setattr(tabs, "open_profile_sessions", lambda profiles=None, checker=None:
                        seen_sessions)
    assert tabs.autorun_tab_seen() == {"/ff/a": True}
    assert tabs.AUTORUN_MARKER in "file:///uivision/ui.vision.html"
