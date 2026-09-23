"""Browser registry — Chrome, the one debuggable browser (2026-09-22).

The Firefox/Edge rows are deleted with the debugger approach (I-62): a normal
Firefox has no debug channel worth driving — its automation runs through the
Ui.Vision extension (`app/browser/uivision`, window "Firefox auto with
Extension") with native OS input instead of a socket. What the registry still
owns: binaries, dir flag, port resolution, launch commands, capabilities and
the Settings scan vocabulary (`ScanNote` / `scan_line`).
"""

import pytest

from app.browser import browsers as br

pytestmark = pytest.mark.unit


def test_the_registry_is_chrome_only_and_still_data_driven():
    assert br.profile_ids() == ["chrome"]
    chrome = br.profile_of("chrome")
    assert chrome.protocol == br.PROTOCOL_CDP
    assert br.profile_of("CHROME").id == "chrome", "ids are case-insensitive"
    assert br.profile_of("firefox") is None, "Firefox is automated by extension, not by socket"
    assert br.profile_of("edge") is None
    assert br.default_profile().id == "chrome"


def test_no_registered_command_reintroduces_a_removed_debugger_flag():
    """Critical-rule guard: the registry vocabulary never grows the deleted flags back."""
    for profile in br.PROFILES:
        cmds = br.launch_commands(profile, br.endpoint(9222, profile.data_dir_default))
        for key, cmd in cmds.items():
            assert "--start-debugger-server" not in cmd, key
            assert "-no-remote" not in cmd, key


def test_the_chrome_row_keeps_its_dir_flag_and_default_dir():
    chrome = br.profile_of("chrome")
    assert chrome.dir_flag == "--user-data-dir"
    assert chrome.data_dir_default
    assert br.default_data_dir("chrome") == chrome.data_dir_default
    assert br.default_data_dir("netscape") == ""


def test_shared_base_port_resolves_to_the_one_endpoint():
    chrome = br.profile_of("chrome")
    assert br.resolve_port(9223, chrome) == 9223
    assert br.resolve_port(9223, chrome, override=9333) == 9333
    assert br.resolve_port(None, chrome) == 9222, "garbage base → default"
    assert br.resolve_port(65535, chrome) == 65535, "never out of range"


def test_chrome_command_carries_binary_dir_flag_port_and_extra_args():
    chrome = br.profile_of("chrome")
    win = br.build_command(chrome, "windows",
                           br.endpoint(9223, "C:\\arena-images-chrome", "--disable-extensions"))
    assert win.startswith('"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"')
    assert "--remote-debugging-port=9223" in win
    assert '--user-data-dir="C:\\arena-images-chrome"' in win
    assert win.endswith("--disable-extensions")


def test_every_browser_gets_commands_for_every_os_and_a_url_variant():
    for profile in br.PROFILES:
        cmds = br.launch_commands(profile, br.endpoint(9222 + profile.port_offset,
                                                       profile.data_dir_default))
        for key in ("windows", "linux", "macos", "windows_with_url", "linux_with_url",
                    "macos_with_url"):
            assert key in cmds and cmds[key], f"{profile.id} missing {key}"
        assert cmds["linux_with_url"].endswith("https://arena.ai")
        assert cmds["windows"] not in (cmds["linux"], cmds["macos"])


def test_capabilities_state_what_the_endpoint_can_do_today():
    chrome = br.profile_of("chrome")
    assert br.capabilities(chrome) == sorted(br.CAPABILITIES)
    for op in ("tabs", "evaluate", "navigate", "screenshot", "set_files", "input", "dom"):
        assert op in br.capabilities(chrome)


def test_every_profile_documents_itself_for_the_panel():
    for profile in br.PROFILES:
        assert profile.label and profile.notes, profile.id


def test_the_scan_vocabulary_names_the_endpoint_and_its_failures():
    line = br.scan_line([{"id": "chrome", "host": "127.0.0.1", "port": 9223,
                          "protocol": "cdp", "enabled": True}])
    assert line == "Scanning: chrome 127.0.0.1:9223 (CDP)"
    off = br.scan_line([{"id": "chrome", "host": "", "port": 9223,
                         "protocol": "cdp", "enabled": False}])
    assert off == "Scanning: chrome — off"
    note = br.ScanNote(browser="chrome", host="127.0.0.1", port=9223, reason="closed")
    assert note.line == "· chrome on 127.0.0.1:9223 — closed"
