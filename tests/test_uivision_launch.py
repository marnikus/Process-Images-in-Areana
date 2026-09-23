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
