"""Browser registry — Firefox next to Chrome, per-browser profile (2026-09-21).

Owner request: same host/port *setting* for both browsers, a separate data dir
and launch command per browser, other browsers addable later, and an honest
answer about what each protocol can do.

RED at `bce5a01`: `app.browser.browsers` did not exist.
"""

import pytest

from app.browser import browsers as br

pytestmark = pytest.mark.unit


def test_the_registry_has_firefox_beside_chrome_and_is_extensible():
    assert br.profile_ids() == ["chrome", "firefox", "edge"]
    chrome, firefox = br.profile_of("chrome"), br.profile_of("firefox")
    assert chrome.protocol == br.PROTOCOL_CDP
    assert firefox.protocol == br.PROTOCOL_BIDI
    assert br.profile_of("CHROME").id == "chrome", "ids are case-insensitive"
    assert br.profile_of("netscape") is None
    assert br.default_profile().id == "chrome", "a fresh install keeps Chrome"


def test_per_browser_data_dirs_and_dir_flags_differ():
    chrome, firefox = br.profile_of("chrome"), br.profile_of("firefox")
    assert chrome.dir_flag == "--user-data-dir"
    assert firefox.dir_flag == "--profile", "Firefox takes a profile dir, not a Chrome dir"
    assert chrome.data_dir_default != firefox.data_dir_default
    assert br.default_data_dir("firefox") == firefox.data_dir_default
    assert br.default_data_dir("netscape") == ""


def test_shared_base_port_resolves_to_one_endpoint_per_browser():
    """Two TCP servers cannot share a port: the shared setting is the BASE."""
    assert br.resolve_port(9223, br.profile_of("chrome")) == 9223
    assert br.resolve_port(9223, br.profile_of("firefox")) == 9224
    assert br.resolve_port(9223, br.profile_of("edge")) == 9225
    assert br.resolve_port(9223, br.profile_of("firefox"), override=9333) == 9333
    assert br.resolve_port(None, br.profile_of("chrome")) == 9222, "garbage base → default"
    assert br.resolve_port(65535, br.profile_of("firefox")) == 65535, "never out of range"


def test_chrome_command_carries_binary_dir_flag_port_and_extra_args():
    chrome = br.profile_of("chrome")
    win = br.build_command(chrome, "windows",
                           br.endpoint(9223, "C:\\arena-images-chrome", "--disable-extensions"))
    assert win.startswith('"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"')
    assert "--remote-debugging-port=9223" in win
    assert '--user-data-dir="C:\\arena-images-chrome"' in win
    assert win.endswith("--disable-extensions")


def test_firefox_command_uses_its_binary_profile_flag_and_no_remote_default():
    firefox = br.profile_of("firefox")
    cmd = br.build_command(firefox, "linux", br.endpoint(9224, "/home/me/.arena-firefox"))
    assert cmd.startswith("firefox ")
    assert "--remote-debugging-port=9224" in cmd
    assert '--profile="/home/me/.arena-firefox"' in cmd
    assert "-no-remote" in cmd, "without it the port never opens while Firefox runs"
    assert "--user-data-dir" not in cmd, "Chrome's flag is meaningless to Firefox"


def test_every_browser_gets_commands_for_every_os_and_a_url_variant():
    for profile in br.PROFILES:
        cmds = br.launch_commands(profile, br.endpoint(9222 + profile.port_offset, profile.data_dir_default))
        for key in ("windows", "linux", "macos", "windows_with_url", "linux_with_url", "macos_with_url"):
            assert key in cmds and cmds[key], f"{profile.id} missing {key}"
        assert cmds["linux_with_url"].endswith("https://arena.ai")
        assert cmds["windows"] not in (cmds["linux"], cmds["macos"])


def test_capabilities_state_what_each_protocol_can_do_today():
    assert br.supports("chrome", "screenshot") is True
    assert br.supports("chrome", "set_files") is True
    assert br.supports("firefox", "tabs") is True
    assert br.supports("firefox", "evaluate") is True
    assert br.supports("firefox", "screenshot") is False, "CDP-only, still missing in BiDi"
    assert br.supports("firefox", "set_files") is False
    assert br.supports("netscape", "tabs") is False
    assert br.supports("firefox", "screenshot", protocol=br.PROTOCOL_CDP) is True, \
        "an ESR Firefox launched with CDP gets the full matrix"
    assert br.capabilities(br.profile_of("chrome")) == sorted(br.CAPABILITIES[br.PROTOCOL_CDP])
    assert br.endpoint_kind("edge") == br.PROTOCOL_CDP
    assert br.endpoint_kind("netscape") == ""


def test_every_profile_documents_itself_for_the_panel():
    for profile in br.PROFILES:
        assert profile.label and profile.notes, profile.id
        assert br.endpoint_kind(profile.id) in br.CAPABILITIES
