"""The browser payload the Settings panel renders — one host/port, Chrome only (2026-09-22).

`get_cdp_config` answers with the whole browser registry (resolved ports, data
dir, launch commands, capabilities) plus the active browser; `set_cdp_config`
takes the active browser and every per-browser block back. The registry holds
one browser now (Firefox/Edge went with the debugger approach, I-62) — the
payload contract is unchanged, and the removed Firefox vocabulary (prefs,
stealth, prepare-profile) must not come back.

The bridge slot count stays frozen — browser support rides payload keys,
not slots.
"""

import json

import pytest

from app.browser import browsers as br
from app.persistence.config_manager import ConfigManager
from app.ui.panels.cdp_tools import CdpToolsMixin
from app.ui.qt_compat import Signal
from tests.test_panel_slots import make_cdp, make_host, make_state

pytestmark = pytest.mark.unit


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def _host(cfg, **attrs):
    host, logs = make_host((CdpToolsMixin,), cdp=None, config=cfg, state=make_state(),
                           highlight_rect=Signal(str), _page_pool=None, **attrs)
    return host, logs


# ── the config payload ──


def test_get_cdp_config_answers_with_the_registry_and_the_active_one(cfg):
    host, _ = _host(cfg)
    payload = json.loads(host.get_cdp_config())
    ids = [b["id"] for b in payload["browsers"]]
    assert ids == ["chrome"], "registry order, Python owns the table"
    assert payload["active_browser"] == "chrome"
    assert payload["host"] == "127.0.0.1" and payload["port"] == 9222
    assert payload["url_pattern"] == "arena.ai"
    assert payload["browser"] == "chrome"
    assert payload["user_data_dir"] == br.default_data_dir("chrome"), "flat fields = active browser"
    assert payload["scan_line"] == "Scanning: chrome 127.0.0.1:9222 (CDP)"
    assert payload["scan_targets"] == [{"id": "chrome", "label": br.profile_of("chrome").label,
                                        "host": "127.0.0.1", "port": 9222, "protocol": "cdp",
                                        "enabled": True}]


def test_the_chrome_row_carries_its_own_port_dir_command_and_capabilities(cfg):
    host, _ = _host(cfg)
    payload = json.loads(host.get_cdp_config())
    chrome = payload["browsers"][0]
    assert chrome["resolved_port"] == 9222
    assert chrome["dir_flag"] == "--user-data-dir"
    os_key = br.current_os()
    assert chrome["binary"] == br.profile_of("chrome").binary(os_key), "the row carries this OS's binary"
    assert "chrome.exe" in chrome["commands"]["windows"]
    assert "--remote-debugging-port=9222" in chrome["commands"]["windows"]
    for key in ("windows", "windows_with_url", "linux", "linux_with_url", "macos", "macos_with_url"):
        assert chrome["commands"][key], f"chrome {key} command missing"
    assert chrome["test_url"].endswith("/json/list")
    assert "screenshot" in chrome["capabilities"] and chrome["unavailable"] == []
    assert chrome["protocol"] == "cdp"
    assert chrome["notes"], "a note explains what the endpoint can do"


def test_the_removed_firefox_vocabulary_never_rides_the_payload(cfg):
    """Round 8-11 keys are gone with the debugger approach — the panel must not wait for them."""
    host, _ = _host(cfg)
    row = json.loads(host.get_cdp_config())["browsers"][0]
    launch = json.loads(host.get_chrome_launch_command())
    for key in ("prefs", "prefs_file", "user_js", "stealth", "debug_flag",
                "profile_dir", "profile_is_default"):
        assert key not in row, f"{key} belonged to the deleted Firefox channel"
        assert key not in launch


# ── saving ──


def test_set_cdp_config_saves_host_base_port_and_the_chrome_row(cfg):
    host, logs = _host(cfg)
    reply = json.loads(host.set_cdp_config(json.dumps({
        "browser": "chrome", "host": "127.0.0.1", "port": 9333, "url_pattern": "arena.ai",
        "browsers": {"chrome": {"enabled": True, "user_data_dir": "D:\\ch"}},
    })))
    assert reply["ok"] is True
    assert reply["browser"] == "chrome"
    assert reply["port"] == 9333, "the reply states the endpoint the browser listens on"
    assert cfg.get_state("active_browser") == "chrome"
    assert cfg.get_state("cdp_port") == 9333, "the shared base port is what got saved"
    assert cfg.get_state("cdp_user_data_dir") == "D:\\ch", \
        "the legacy flat pair keeps tracking the DEFAULT browser (pre-multi-browser readers)"
    assert cfg.get_state("cdp_browsers")["chrome"]["user_data_dir"] == "D:\\ch"
    assert any("chrome" in msg for _lvl, msg in logs)


def test_saving_pushes_the_endpoint_to_the_client_and_the_pool(cfg):
    host, _ = _host(cfg)
    host.cdp = make_cdp(connected=True)
    pushed = []
    host.cdp.set_host_port = lambda h, p: pushed.append((h, p))
    pool = type("Pool", (), {"_host": "", "_port": 0, "_browser": ""})()
    host._page_pool = pool
    host.set_cdp_config(json.dumps({"browser": "chrome", "host": "127.0.0.1", "port": 9500}))
    assert pushed == [("127.0.0.1", 9500)], "the live client follows the saved endpoint"
    assert (pool._host, pool._port) == ("127.0.0.1", 9500)
    assert pool._browser == "chrome", "pool rows carry the browser the endpoint belongs to"


def test_an_unknown_browser_is_refused_by_name(cfg):
    host, _ = _host(cfg)
    for wanted in ("netscape", "firefox", "edge"):
        reply = json.loads(host.set_cdp_config(json.dumps({"browser": wanted, "port": 9222})))
        assert reply["ok"] is False and wanted in reply["error"], \
            f"{wanted} is not registered — the refusal must name it"
    assert cfg.get_state("active_browser") == "chrome", "a rejected save changes nothing"


def test_empty_per_browser_fields_never_erase_the_stored_ones(cfg):
    host, _ = _host(cfg)
    host.set_cdp_config(json.dumps({"browser": "chrome", "port": 9222,
                                    "browsers": {"chrome": {"user_data_dir": "", "extra_args": ""}}}))
    assert cfg.get_state("cdp_browsers")["chrome"]["user_data_dir"] == br.default_data_dir("chrome")


def test_the_prepare_profile_request_is_ignored_by_name(cfg):
    """The Firefox profile writer is deleted — the flag must not resurrect a branch."""
    host, _ = _host(cfg)
    reply = json.loads(host.set_cdp_config(json.dumps({"browser": "chrome", "port": 9222,
                                                       "prepare_profile": True})))
    assert reply["ok"] is True
    assert "prepare_profile" not in reply


# ── the launch command slot ──


def test_get_chrome_launch_command_follows_the_saved_settings(cfg):
    host, _ = _host(cfg)
    host.set_cdp_config(json.dumps({"browser": "chrome", "port": 9229, "url_pattern": "arena.ai"}))
    launch = json.loads(host.get_chrome_launch_command())
    assert launch["browser"] == "chrome" and launch["protocol"] == "cdp"
    assert launch["resolved_port"] == 9229
    assert "chrome.exe" in launch["windows"]
    assert "--remote-debugging-port=9229" in launch["windows"]
    assert launch["macos"] and launch["linux_with_url"]
    assert "9229" in launch["test_url"] and launch["unavailable"] == []
    assert launch["url_pattern"] == "arena.ai"


def test_the_shared_port_stays_one_setting(cfg):
    host, _ = _host(cfg)
    host.set_cdp_config(json.dumps({"browser": "chrome", "port": 9229}))
    after = json.loads(host.get_cdp_config())
    assert (after["port"], after["browsers"][0]["resolved_port"]) == (9229, 9229), \
        "one base port, one endpoint"


def test_browser_support_added_payloads_not_bridge_slots():
    from tests.test_bridge_slots import FROZEN_SLOTS

    assert len(FROZEN_SLOTS) == 143, ("browser support added payloads; I-63 added the 4 firefox_auto slots + "
                                      "show_firefox_profiles (2026-09-24); I-64 added set_page_jobs (2026-09-25)")
    for slot in ("get_cdp_config", "set_cdp_config", "get_chrome_launch_command"):
        assert slot in FROZEN_SLOTS
    assert not (FROZEN_SLOTS & {"get_browser_config", "set_browser_config", "list_browsers",
                                "get_browser_launch_command"}), "browser support rides the CDP slots"
