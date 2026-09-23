"""The Firefox launch line — exactly [binary, url], debugger vocabulary banned.

The owner's critical rules as tests: the argv never grows a third element, and
the deleted approach's words (debugger server, remote debugging, -no-remote,
geckodriver/Selenium/Playwright/Puppeteer, marionette) are refused by name.
"""

import pytest

from app.browser.uivision import launch

pytestmark = pytest.mark.unit


def test_argv_is_exactly_binary_and_url():
    argv = launch.build_argv("/usr/bin/firefox", "file:///tmp/ui.vision.html?macro=X")
    assert argv == ["/usr/bin/firefox", "file:///tmp/ui.vision.html?macro=X"]


def test_banned_vocabulary_is_refused_wherever_it_rides():
    for marker in launch.BANNED_ARG_MARKERS:
        with pytest.raises(ValueError, match="debugger/driver"):
            launch.build_argv(f"/usr/bin/firefox --{marker}", "file:///x")
        with pytest.raises(ValueError, match="debugger/driver"):
            launch.build_argv("/usr/bin/firefox", f"file:///x?{marker}=1")


def test_banned_marker_table_is_pinned():
    assert set(launch.BANNED_ARG_MARKERS) == {
        "start-debugger-server", "remote-debugging-port", "no-remote", "geckodriver",
        "selenium", "playwright", "puppeteer", "marionette"}


def test_resolve_binary_prefers_the_configured_path():
    assert launch.resolve_binary('  "/opt/ff/firefox"  ') == "/opt/ff/firefox"
    assert launch.resolve_binary("", "windows") == launch.DEFAULT_BINARIES["windows"]
    assert launch.resolve_binary("", "linux") == "firefox"
    assert launch.resolve_binary("", "macos") == launch.DEFAULT_BINARIES["macos"]
    assert launch.resolve_binary("", "plan9") == launch.DEFAULT_BINARIES["linux"]  # fallback


def test_binary_exists_checks_paths_and_trusts_path_names(tmp_path):
    real = tmp_path / "firefox"
    real.write_text("#!/bin/sh\n")
    assert launch.binary_exists(str(real)) is True
    assert launch.binary_exists(str(tmp_path / "nope")) is False
    assert launch.binary_exists(str(tmp_path)) is False  # a folder is not launchable
    assert launch.binary_exists("sh") is True            # bare name → which
    assert launch.binary_exists("definitely_not_here_xyz") is False


def test_launch_uses_the_popen_seam():
    seen = []
    handle = launch.launch(["firefox", "file:///x"], popen=lambda argv: seen.append(argv) or "proc")
    assert handle == "proc"
    assert seen == [["firefox", "file:///x"]]


def test_launch_defaults_to_subprocess_popen(monkeypatch):
    seen = []
    monkeypatch.setattr(launch.subprocess, "Popen", lambda argv: seen.append(argv) or "proc")
    assert launch.launch(["firefox", "file:///x"]) == "proc"
    assert seen == [["firefox", "file:///x"]]


def test_diagnose_binary_names_the_fix_per_case(tmp_path):
    real = tmp_path / "firefox"
    real.write_text("#!/bin/sh\n")
    assert "FULL" in launch.diagnose_binary("") and "where firefox" in launch.diagnose_binary("")
    folder_line = launch.diagnose_binary(str(tmp_path))
    assert "FOLDER" in folder_line and "WinError 5" in folder_line
    missing = launch.diagnose_binary(str(tmp_path / "nope"))
    assert "no file" in missing and "where firefox" in missing
    refused = launch.diagnose_binary(str(real))
    assert "exists" in refused and "refused to start" in refused


def test_launch_resilient_passes_through_on_success():
    handle = launch.launch_resilient(["firefox", "file:///x"], popen=lambda argv: "proc")
    assert handle == "proc"


def test_launch_resilient_wraps_a_seam_refusal_without_fallbacks(tmp_path):
    binary = tmp_path / "firefox"
    binary.write_text("#!/bin/sh\n")

    def refuse(_argv):
        raise PermissionError("[WinError 5] Access is denied")

    with pytest.raises(launch.LaunchError, match="would not start") as caught:
        launch.launch_resilient([str(binary), "file:///x"], popen=refuse)
    assert "[WinError 5]" in str(caught.value)
    assert "exists" in str(caught.value)              # the binary's own diagnosis rides along
    assert isinstance(caught.value, OSError)          # the runner catches OSError


def test_launch_resilient_falls_back_through_windows_launchers(monkeypatch):
    import os
    calls = []

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        if not kwargs:
            raise PermissionError("[WinError 5] Access is denied")
        return "proc-from-own-folder"

    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch.subprocess, "Popen", popen)
    handle = launch.launch_resilient([os.path.join("C:\\", "ff", "firefox.exe"), "file:///x"])
    assert handle == "proc-from-own-folder"
    assert len(calls) == 2                            # plain Popen, then executable=+cwd=
    assert calls[1][1]["executable"].endswith("firefox.exe")
    assert calls[1][1]["cwd"].endswith("ff")


def test_launch_resilient_shell_open_is_the_last_resort_before_the_error(monkeypatch):
    import os
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    monkeypatch.setattr(launch, "_shell_execute", lambda binary, url: "proc-from-shell")
    assert launch.launch_resilient(["C:\\ff\\firefox.exe", "file:///x"]) == "proc-from-shell"

    monkeypatch.setattr(launch, "_shell_execute",
                        lambda binary, url: (_ for _ in ()).throw(OSError("no shell")))
    started = []
    monkeypatch.setattr(launch.os, "startfile", lambda url: started.append(url), raising=False)
    handle = launch.launch_resilient(["C:\\ff\\firefox.exe", "file:///u.vision"])
    assert handle.pid == "?" and started == ["file:///u.vision"]

    monkeypatch.delattr(launch.os, "startfile", raising=False)
    with pytest.raises(launch.LaunchError, match="would not start"):
        launch.launch_resilient(["C:\\ff\\firefox.exe", "file:///x"])


def test_candidate_binaries_per_os(monkeypatch):
    import os
    monkeypatch.setenv("ProgramFiles", "/opt/pf")
    monkeypatch.setenv("ProgramFiles(x86)", "")
    monkeypatch.setenv("LOCALAPPDATA", "/opt/la")
    win = launch.candidate_binaries("windows")
    assert win[0] == os.path.join("/opt/pf", "Mozilla Firefox", "firefox.exe")
    fallback = os.path.join(r"C:\Program Files (x86)", "Mozilla Firefox", "firefox.exe")
    assert fallback in win and os.path.join("/opt/la", "Mozilla Firefox", "firefox.exe") in win
    assert launch.candidate_binaries("macos") == [
        "/Applications/Firefox.app/Contents/MacOS/firefox"]
    assert launch.candidate_binaries("linux")[:2] == ["firefox", "/usr/bin/firefox"]
