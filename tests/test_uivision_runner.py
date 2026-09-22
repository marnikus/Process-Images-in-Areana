"""I-65 · launching Firefox and polling for the verdict.

Two guarantees are pinned here:

* Firefox is launched as a **normal browser** — no debugger port, no
  marionette, no headless. That absence is the entire point of replacing the
  RDP approach, so it is asserted on the real argv.
* A macro that never finishes is reported as a timeout, never raised and never
  silently treated as success.
"""

import asyncio

import pytest

from app.browser.uivision import runner
from app.browser.uivision.command_url import MacroRun
from app.browser.uivision.run_log import FAILED, OK, PENDING


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def spawned(monkeypatch):
    """Capture the argv instead of actually starting a browser."""
    calls = []
    monkeypatch.setattr(runner, "_spawn", lambda argv: calls.append(argv))
    return calls


class TestLaunchArgv:
    def test_it_opens_a_new_tab_in_the_users_browser(self):
        argv = runner.launch_argv("firefox", "file:///x/ui.vision.html?macro=M")
        assert argv == ["firefox", "-new-tab", "file:///x/ui.vision.html?macro=M"]

    def test_nothing_else_is_ever_added(self):
        # no -profile, no -no-remote: the user's normal session is reused
        assert len(runner.launch_argv("firefox", "file:///x")) == 3

    @pytest.mark.parametrize("flag", ["--start-debugger-server", "--marionette",
                                      "--remote-debugging-port", "--headless"])
    def test_automation_flags_are_refused(self, flag):
        # these are exactly what made the old Firefox path detectable
        with pytest.raises(ValueError, match="automation"):
            runner.launch_argv(flag, "file:///x")

    def test_a_flag_with_a_value_is_still_refused(self):
        with pytest.raises(ValueError):
            runner.launch_argv("--remote-debugging-port=9222", "file:///x")

    def test_the_banned_list_covers_the_debugger_channel(self):
        assert "--start-debugger-server" in runner.LAUNCH_BANNED_FLAGS


class TestRunMacro:
    def cfg(self, tmp_path, **kw):
        kw.setdefault("macro", "Python_XClick_Demo")
        kw.setdefault("html_path", "/rpa/ui.vision.html")
        kw.setdefault("log_path", str(tmp_path / "uiv.log"))
        return MacroRun(**kw)

    def test_a_completed_macro_reports_ok(self, tmp_path, spawned, monkeypatch):
        log = tmp_path / "uiv.log"
        monkeypatch.setattr(runner, "_spawn",
                            lambda argv: log.write_text("[status] Macro completed"))
        out = run(runner.run_macro(self.cfg(tmp_path), timeout=2))
        assert out.ok and out.state == OK

    def test_a_failed_macro_reports_the_error_line(self, tmp_path, monkeypatch):
        log = tmp_path / "uiv.log"
        monkeypatch.setattr(runner, "_spawn",
                            lambda argv: log.write_text("[error] element not found"))
        out = run(runner.run_macro(self.cfg(tmp_path), timeout=2))
        assert out.state == FAILED and "not found" in out.message

    def test_a_macro_that_never_finishes_times_out(self, tmp_path, spawned):
        # no log is ever written — must report, not hang or raise
        out = run(runner.run_macro(self.cfg(tmp_path), timeout=0.2))
        assert out.timed_out and out.state == PENDING and not out.ok

    def test_the_timeout_message_names_the_usual_cause(self, tmp_path, spawned):
        out = run(runner.run_macro(self.cfg(tmp_path), timeout=0.2))
        assert "XModules" in out.message or "installed" in out.message

    def test_the_browser_is_launched_with_the_autorun_url(self, tmp_path, spawned):
        run(runner.run_macro(self.cfg(tmp_path), binary="firefox", timeout=0.2))
        assert spawned and spawned[0][0] == "firefox"
        assert spawned[0][-1].startswith("file:///rpa/ui.vision.html?")

    def test_a_stale_log_is_cleared_before_the_run(self, tmp_path, spawned):
        # the previous run's "completed" must not be mistaken for this one's
        log = tmp_path / "uiv.log"
        log.write_text("[status] Macro completed")
        out = run(runner.run_macro(self.cfg(tmp_path), timeout=0.2))
        assert out.timed_out, "read the stale verdict instead of clearing it"

    def test_an_incomplete_config_never_launches_a_browser(self, tmp_path, spawned):
        out = run(runner.run_macro(MacroRun("", "", str(tmp_path / "l.log"))))
        assert out.state == FAILED and spawned == []

    def test_a_missing_browser_is_reported_not_raised(self, tmp_path, monkeypatch):
        def boom(argv):
            raise OSError("No such file or directory: 'firefox'")
        monkeypatch.setattr(runner, "_spawn", boom)
        out = run(runner.run_macro(self.cfg(tmp_path), timeout=0.2))
        assert out.state == FAILED and "firefox" in out.message

    def test_the_outcome_carries_the_log_tail(self, tmp_path, monkeypatch):
        log = tmp_path / "uiv.log"
        monkeypatch.setattr(runner, "_spawn",
                            lambda argv: log.write_text("[info] step 1\n[status] Macro completed"))
        out = run(runner.run_macro(self.cfg(tmp_path), timeout=2))
        assert "[info] step 1" in (out.lines or [])


class TestPollVerdict:
    def test_it_returns_as_soon_as_the_verdict_appears(self, tmp_path):
        log = tmp_path / "uiv.log"

        async def scenario():
            task = asyncio.ensure_future(runner.poll_verdict(log, timeout=5, interval=0.05))
            await asyncio.sleep(0.1)
            log.write_text("[status] Macro completed")
            return await task

        assert run(scenario()).ok

    def test_it_gives_up_at_the_deadline(self, tmp_path):
        out = run(runner.poll_verdict(tmp_path / "none.log", timeout=0.15, interval=0.05))
        assert out.state == PENDING


class TestFindFirefox:
    def test_it_returns_the_resolved_binary(self, monkeypatch):
        monkeypatch.setattr(runner.shutil, "which",
                            lambda name: "/usr/bin/firefox" if name == "firefox" else None)
        assert runner.find_firefox() == "/usr/bin/firefox"

    def test_it_is_empty_when_firefox_is_absent(self, monkeypatch):
        monkeypatch.setattr(runner.shutil, "which", lambda name: None)
        assert runner.find_firefox() == ""


class TestSpawn:
    def test_it_starts_the_browser_detached(self, monkeypatch):
        # the macro runs in the tab; waiting for firefox to exit would hang
        seen = {}

        class FakePopen:
            def __init__(self, argv, **kw):
                seen.update(argv=argv, kw=kw)

        monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)
        runner._spawn(["firefox", "-new-tab", "file:///x"])
        assert seen["argv"][0] == "firefox"
        assert seen["kw"]["stdout"] == runner.subprocess.DEVNULL


class TestUnclearableLog:
    def test_a_log_that_cannot_be_cleared_stops_the_run(self, tmp_path, spawned):
        # without a fresh log the poller would read the previous verdict, so
        # refusing to launch is the only honest outcome
        out = run(runner.run_macro(MacroRun("M", "/r/ui.vision.html", str(tmp_path)),
                                   timeout=0.2))
        assert out.state == FAILED and "cannot clear log" in out.message
        assert spawned == [], "must not launch a browser it cannot get a verdict from"
