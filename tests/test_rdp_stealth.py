"""The anti-detection constraints, as executable checks (I-62).

`navigator.webdriver` is true iff Marionette or the Remote Agent is running
(`dom/base/Navigator.cpp`). The DevTools server that `--start-debugger-server`
starts is a third mechanism the property never consults — these tests pin that
distinction so nobody "fixes" the launch command back into a detectable one.
"""

import pytest

from app.browser.rdp import click_js
from app.browser.rdp.stealth import (forbidden_flags, launch_command, required_prefs,
                                     stealth_warnings)

pytestmark = pytest.mark.unit


def test_the_launch_command_uses_the_devtools_server_and_a_real_profile():
    argv = launch_command("/usr/bin/firefox", "daily", 6000)
    assert argv == ["/usr/bin/firefox", "-P", "daily", "--start-debugger-server", "6000"]
    assert forbidden_flags(argv) == []


def test_the_launch_command_never_asks_for_headless_or_a_driver():
    argv = launch_command("firefox", "daily")
    assert not {"--headless", "--marionette", "--remote-debugging-port"} & set(argv)


def test_a_profileless_command_still_works():
    assert launch_command("firefox", "") == ["firefox", "--start-debugger-server", "6000"]


def test_a_blank_binary_falls_back_to_firefox():
    assert launch_command("", "p")[0] == "firefox"


@pytest.mark.parametrize("flag, expected", [
    ("--marionette", "--marionette"),
    ("-marionette", "--marionette"),            # Windows single-dash spelling
    ("--MARIONETTE", "--marionette"),           # Firefox flags are case-insensitive
    ("--remote-debugging-port=9222", "--remote-debugging-port"),  # =value form
    ("--headless", "--headless"),
])
def test_every_automation_exposing_flag_is_caught_in_any_spelling(flag, expected):
    assert forbidden_flags(["firefox", flag]) == [expected]


def test_the_devtools_flag_is_not_treated_as_an_automation_signal():
    """The whole premise: this flag does NOT set navigator.webdriver."""
    assert forbidden_flags(["firefox", "--start-debugger-server", "6000"]) == []


def test_marionette_and_the_remote_agent_are_both_rejected():
    found = forbidden_flags(["firefox", "--marionette", "--remote-debugging-port=9222"])
    assert found == ["--marionette", "--remote-debugging-port"]


def test_an_empty_command_line_is_clean_not_broken():
    assert forbidden_flags([]) == [] and forbidden_flags(["", "--"]) == []


def test_the_required_prefs_are_the_three_devtools_server_prefs():
    assert required_prefs() == {"devtools.debugger.remote-enabled": True,
                                "devtools.chrome.enabled": True,
                                "devtools.debugger.prompt-connection": False}


def test_required_prefs_hands_back_a_copy():
    required_prefs()["devtools.chrome.enabled"] = False
    assert required_prefs()["devtools.chrome.enabled"] is True


def test_a_clean_session_produces_no_warnings():
    argv = launch_command("firefox", "daily")
    assert stealth_warnings(argv, {"webdriver": False, "hasCdc": False}) == []


def test_a_bad_flag_and_a_tripped_signal_are_both_reported():
    lines = stealth_warnings(["firefox", "--marionette"], {"webdriver": True, "hasCdc": True})
    assert len(lines) == 3
    assert any("--marionette" in line for line in lines)
    assert any("navigator.webdriver" in line for line in lines)
    assert any("cdc_" in line for line in lines)


def test_unknown_signal_keys_are_ignored_rather_than_guessed_at():
    assert stealth_warnings(["firefox"], {"somethingElse": True}) == []


def test_missing_signals_are_not_invented():
    assert stealth_warnings(["firefox"], None) == []


def test_the_click_payload_dispatches_a_real_pointer_sequence():
    js = click_js.build_click_js("#send")
    for event in ("pointerdown", "mousedown", "pointerup", "mouseup", "click"):
        assert event in js
    assert "scrollIntoView" in js


def test_the_selector_is_injected_as_a_json_literal():
    """A quote in a selector must not be able to close the string and inject JS."""
    js = click_js.build_click_js('a[title="x"]')
    assert '"a[title=\\"x\\"]"' in js
    assert js.count("querySelector(") == 1


def test_the_probe_payload_never_clicks():
    js = click_js.build_probe_js("#a")
    assert "dispatchEvent" not in js and "getBoundingClientRect" in js


def test_the_signal_probe_reads_what_the_site_reads():
    js = click_js.build_webdriver_probe_js()
    assert "navigator.webdriver" in js and "cdc_" in js
