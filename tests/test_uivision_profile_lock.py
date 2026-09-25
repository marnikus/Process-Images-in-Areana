"""The open-profile gate — the profile lock Firefox itself holds (2026-09-24,
rebuilt 2026-09-25 after the `lock.ini` assumption proved wrong).

Source of truth: `toolkit/profile/nsProfileLock.cpp` in
`mozilla-firefox/firefox` (read 2026-09-25; the frozen 2025-07 gecko-dev
mirror and 2015/2019 vintages agree). Windows holds an EMPTY `parent.lock`
open with no sharing (the exclusive handle IS the receipt — the file is
never deleted); unix holds `fcntl(F_WRLCK)` on the persistent `.parentlock`,
plus the legacy `lock` SYMLINK `<ip>:<pid>` from old builds. The OS syscalls
are faked here; the reason strings are pinned because the report lines quote
them verbatim.
"""

import ctypes
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.browser.uivision import profile_lock, tabs

pytestmark = pytest.mark.unit


# ── the Windows probe: open without sharing, a live holder is the receipt ──

class FakeKernel32:
    def __init__(self, handle=1, last_error=32):
        self.handle, self.last_error = handle, last_error
        self.closed = []
        self.CreateFileW = self._make_create()       # a function: takes `restype`

    def _make_create(self):
        def create(path, access, share, sa, disp, flags, template):
            assert share == 0 and disp == profile_lock._OPEN_EXISTING
            return self.handle
        return create

    def GetLastError(self):
        return self.last_error

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


def test_windows_probe_sharing_violation_means_running(monkeypatch):
    kernel = FakeKernel32(handle=ctypes.c_void_p(-1).value, last_error=32)
    monkeypatch.setattr(ctypes, "windll", kernel, raising=False)
    assert profile_lock._held_windows("C:\\ff\\a\\parent.lock") is True
    assert kernel.closed == []                      # nothing was opened


def test_windows_probe_access_denied_means_running(monkeypatch):
    kernel = FakeKernel32(handle=ctypes.c_void_p(-1).value, last_error=5)
    monkeypatch.setattr(ctypes, "windll", kernel, raising=False)
    assert profile_lock._held_windows("C:\\ff\\a\\parent.lock") is True


def test_windows_probe_clean_open_means_not_running(monkeypatch):
    kernel = FakeKernel32(handle=1, last_error=2)
    monkeypatch.setattr(ctypes, "windll", kernel, raising=False)
    assert profile_lock._held_windows("C:\\ff\\a\\parent.lock") is False
    assert kernel.closed == [1]                     # our probe handle released


def test_windows_probe_missing_file_means_not_running(monkeypatch):
    kernel = FakeKernel32(handle=ctypes.c_void_p(-1).value, last_error=2)
    monkeypatch.setattr(ctypes, "windll", kernel, raising=False)
    assert profile_lock._held_windows("C:\\ff\\a\\parent.lock") is False


def test_windows_probe_without_windll_is_not_running(monkeypatch):
    monkeypatch.delattr(ctypes, "windll", raising=False)
    assert profile_lock._held_windows("C:\\ff\\a\\parent.lock") is False


# ── the unix probe: F_GETLK on the persistent .parentlock ──────────────────

def _flock_raw(l_type: int, l_pid: int = 0) -> bytes:
    fr = profile_lock._Flock()
    fr.l_type, fr.l_pid = l_type, l_pid
    return bytes(fr)


def test_module_imports_without_the_fcntl_module():
    """The Windows regression (2026-09-25): `import fcntl` fails on Windows, and
    the app died at `save_firefox_auto_config` — the whole uivision chain must
    import cleanly when the module is absent."""
    code = (
        "import sys; sys.modules['fcntl'] = None\n"
        "from app.browser.uivision import profile_lock, runner, tabs\n"
        "assert profile_lock._held_windows('C:\\\\ff\\\\a\\\\parent.lock') is False\n"
        "print('ok')\n"
    )
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-c", code], cwd=repo_root,
                          capture_output=True, text=True)
    assert proc.returncode == 0 and "ok" in proc.stdout, proc.stderr


@pytest.mark.skipif(os.name == "nt", reason="fcntl lock probe is unix-only")
def test_fcntl_probe_missing_file_is_not_running(tmp_path):
    assert profile_lock._held_fcntl(tmp_path / "absent") is False


@pytest.mark.skipif(os.name == "nt", reason="fcntl lock probe is unix-only")
def test_fcntl_probe_unlocked_file_is_not_running(tmp_path):
    """The real F_GETLK: nothing held → F_UNLCK → not running."""
    path = tmp_path / ".parentlock"
    path.write_text("", encoding="utf-8")
    assert profile_lock._held_fcntl(path) is False


@pytest.mark.skipif(os.name == "nt", reason="fcntl lock probe is unix-only")
def test_fcntl_probe_held_lock_is_running(tmp_path, monkeypatch):
    """F_GETLK's answer bytes carrying F_WRLCK → running (holder named)."""
    import fcntl as fcntl_module
    path = tmp_path / ".parentlock"
    path.write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setattr(fcntl_module, "fcntl",
                        lambda fd, cmd, arg: calls.append(cmd) or _flock_raw(1, 4242))
    assert profile_lock._held_fcntl(path) is True
    assert calls == [profile_lock._F_GETLK]


@pytest.mark.skipif(os.name == "nt", reason="fcntl lock probe is unix-only")
def test_fcntl_probe_size_mismatch_is_not_running(tmp_path, monkeypatch):
    import fcntl as fcntl_module
    path = tmp_path / ".parentlock"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(fcntl_module, "fcntl", lambda fd, cmd, arg: b"\x01\x00")
    assert profile_lock._held_fcntl(path) is False


# ── the legacy unix symlink: <ip>:<pid>, a "+" pid is obsolete ─────────────

def _symlink(profile, target):
    link = profile / profile_lock.LEGACY_LINK
    link.unlink(missing_ok=True)
    link.symlink_to(target)


def test_legacy_link_pid_parses_the_ip_pid_form(tmp_path):
    _symlink(tmp_path, "192.168.1.4:1234")
    assert profile_lock._legacy_link_pid(tmp_path) == 1234


def test_legacy_link_pid_rejects_the_obsolete_plus_form(tmp_path):
    _symlink(tmp_path, "192.168.1.4:+1234")
    assert profile_lock._legacy_link_pid(tmp_path) is None


def test_legacy_link_pid_none_when_absent_or_garbage(tmp_path):
    assert profile_lock._legacy_link_pid(tmp_path) is None
    _symlink(tmp_path, "not-an-ip-and-pid")
    assert profile_lock._legacy_link_pid(tmp_path) is None


# ── profile_open: the gate + its frozen reasons ────────────────────────────

def test_profile_open_held_current_lock_is_running(tmp_path):
    (tmp_path / profile_lock.LOCK_FILES[0]).write_text("", encoding="utf-8")
    got = profile_lock.profile_open(tmp_path, checker=lambda path: True)
    assert got == (True, f"{profile_lock.LOCK_FILES[0]} held — running")


def test_profile_open_unlocked_current_lock_is_not_running(tmp_path):
    (tmp_path / profile_lock.LOCK_FILES[0]).write_text("", encoding="utf-8")
    got = profile_lock.profile_open(tmp_path, checker=lambda path: False)
    assert got == (False, f"{profile_lock.LOCK_FILES[0]} not held — not running")


def test_profile_open_falls_through_to_the_second_lock_name(tmp_path):
    (tmp_path / profile_lock.LOCK_FILES[1]).write_text("", encoding="utf-8")
    got = profile_lock.profile_open(tmp_path, checker=lambda path: True)
    assert got == (True, f"{profile_lock.LOCK_FILES[1]} held — running")


def test_profile_open_no_lock_file_at_all(tmp_path):
    assert profile_lock.profile_open(tmp_path, checker=lambda path: True) == \
        (False, "no lock file — not running")


@pytest.mark.skipif(os.name == "nt", reason="the real probe is unix here")
def test_profile_open_real_probe_without_a_holder_is_not_running(tmp_path):
    """End to end on this host: the lock file exists, no process holds it."""
    path = tmp_path / ".parentlock"
    path.write_text("", encoding="utf-8")
    assert profile_lock.profile_open(tmp_path) == (
        False, ".parentlock not held — not running")


@pytest.mark.skipif(os.name == "nt", reason="the legacy symlink is unix-only")
def test_profile_open_legacy_symlink_decides_when_no_lock_file(tmp_path):
    _symlink(tmp_path, f"127.0.0.1:{os.getpid()}")
    got = profile_lock.profile_open(tmp_path)
    assert got == (True, f"legacy lock pid {os.getpid()} alive — running")
    _symlink(tmp_path, "127.0.0.1:99999999")
    got = profile_lock.profile_open(tmp_path)
    assert got == (False, "legacy lock pid 99999999 not running — stale")


# ── the tabs-level open filter ──────────────────────────────────────────────

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
        return ((checker or (lambda path: True))(d), "")  # /ff/a: open iff it says

    monkeypatch.setattr(tabs, "profile_open", fake_open)
    open_sessions = tabs.open_profile_sessions()
    assert [s["dir"] for s in open_sessions] == ["/ff/a"]
    # the checker seam rides through to profile_open, once per closed-out candidate
    seen = []
    tabs.open_profile_sessions(checker=lambda path: (seen.append(path), True)[1])
    assert seen == ["/ff/a"]


def test_profile_open_states_reports_every_dir_with_its_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(tabs, "profile_dirs", lambda: ["/ff/a", "/ff/b", "/ff/c"])
    monkeypatch.setattr(tabs, "profile_names", lambda: {tabs.Path("/ff/a"): "Work"})
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (
        d == "/ff/a",
        "parent.lock held — running" if d == "/ff/a" else "no lock file — not running"))
    states = tabs.profile_open_states()
    assert states == [("/ff/a", "Work", True, "parent.lock held — running"),
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
