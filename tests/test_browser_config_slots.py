"""The browser payloads the panel renders — one host/port, two browsers (2026-09-21).

`get_cdp_config` now answers with the whole browser registry (resolved ports,
per-browser data dir, launch commands, capabilities) plus the active browser, so
the Settings block can cover Chrome AND Firefox without a new bridge slot;
`set_cdp_config` takes the active browser and every per-browser block back.

The bridge slot count stays frozen at 119 — browser support adds payload keys,
not slots.

RED at `bce5a01`: the payloads had no `browsers` key.
"""

import json

import pytest
from PySide6.QtCore import Signal

from app.browser import browsers as br
from app.persistence.config_manager import ConfigManager
from app.ui.panels.cdp_tools import CdpToolsMixin
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


def test_get_cdp_config_answers_with_every_browser_and_the_active_one(cfg):
    host, _ = _host(cfg)
    payload = json.loads(host.get_cdp_config())
    ids = [b["id"] for b in payload["browsers"]]
    assert ids == ["chrome", "firefox", "edge"], "registry order, Python owns the table"
    assert payload["active_browser"] == "chrome", "a fresh install keeps Chrome"
    assert payload["host"] == "127.0.0.1" and payload["port"] == 9222
    assert payload["url_pattern"] == "arena.ai", "one pattern for every browser"
    assert payload["browser"] == "chrome"
    assert payload["user_data_dir"] == br.default_data_dir("chrome"), "flat fields = active browser"


def test_each_browser_row_carries_its_own_port_dir_command_and_capabilities(cfg):
    host, _ = _host(cfg)
    payload = json.loads(host.get_cdp_config())
    by_id = {b["id"]: b for b in payload["browsers"]}
    chrome, firefox = by_id["chrome"], by_id["firefox"]
    assert chrome["resolved_port"] == 9222 and firefox["resolved_port"] == 9223, "base + offset"
    assert chrome["user_data_dir"] != firefox["user_data_dir"]
    assert chrome["dir_flag"] == "--user-data-dir" and firefox["dir_flag"] == "--profile"
    os_key = br.current_os()
    assert chrome["binary"] == br.profile_of("chrome").binary(os_key), "the row carries this OS's binary"
    assert firefox["binary"] == br.profile_of("firefox").binary(os_key)
    assert "chrome.exe" in chrome["commands"]["windows"]
    assert "--start-debugger-server=9223" in firefox["commands"]["windows"]
    assert "--remote-debugging-port" not in firefox["commands"]["windows"], \
        "stealth: the tainting flag must never appear in a Firefox command"
    assert "-no-remote" in firefox["commands"]["windows"], "or the port never opens"
    for key in ("windows", "windows_with_url", "linux", "linux_with_url", "macos", "macos_with_url"):
        assert firefox["commands"][key], f"firefox {key} command missing"
    assert chrome["test_url"].endswith("/json/list")
    assert firefox["test_url"] == "tcp://127.0.0.1:9223", "RDP is plain TCP, no HTTP surface"
    assert "screenshot" in chrome["capabilities"] and chrome["unavailable"] == []
    assert "screenshot" in firefox["unavailable"], "the panel must be able to name the gap"
    assert firefox["protocol"] == "rdp" and chrome["protocol"] == "cdp"
    assert firefox["debug_arg"] == "--start-debugger-server"
    assert firefox["notes"], "a note explains the protocol / the ESR CDP path"


# ── saving ──


def test_set_cdp_config_switches_the_active_browser_and_keeps_its_port(cfg):
    host, logs = _host(cfg)
    reply = json.loads(host.set_cdp_config(json.dumps({
        "browser": "firefox", "host": "127.0.0.1", "port": 9333, "url_pattern": "arena.ai",
        "user_data_dir": "D:\\ff", "extra_args": "-no-remote",
        "browsers": {"chrome": {"enabled": True, "user_data_dir": "D:\\ch"},
                     "firefox": {"enabled": True, "user_data_dir": "D:\\ff", "extra_args": "-no-remote"}},
    })))
    assert reply["ok"] is True
    assert reply["browser"] == "firefox"
    assert reply["port"] == 9334, "the reply states the endpoint the browser actually listens on"
    assert cfg.get_state("active_browser") == "firefox"
    assert cfg.get_state("cdp_port") == 9333, "the shared base port is what got saved"
    assert cfg.get_state("cdp_user_data_dir") == "D:\\ch", \
        "the legacy flat pair keeps tracking the DEFAULT browser (pre-multi-browser readers)"
    assert cfg.get_state("cdp_browsers")["chrome"]["user_data_dir"] == "D:\\ch"
    assert cfg.get_state("cdp_browsers")["firefox"]["user_data_dir"] == "D:\\ff"
    assert any("firefox" in msg for _lvl, msg in logs)


def test_saving_pushes_the_active_browsers_endpoint_to_the_client_and_the_pool(cfg):
    host, _ = _host(cfg)
    host.cdp = make_cdp(connected=True)
    pushed = []
    host.cdp.set_host_port = lambda h, p: pushed.append((h, p))
    pool = type("Pool", (), {"_host": "", "_port": 0, "_browser": ""})()
    host._page_pool = pool
    host.set_cdp_config(json.dumps({"browser": "firefox", "host": "127.0.0.1", "port": 9500}))
    assert pushed == [("127.0.0.1", 9501)], "the live client follows the selected browser"
    assert (pool._host, pool._port) == ("127.0.0.1", 9501)
    assert pool._browser == "firefox", "pool rows carry the browser the endpoint belongs to"


def test_an_unknown_browser_is_refused_by_name(cfg):
    host, _ = _host(cfg)
    reply = json.loads(host.set_cdp_config(json.dumps({"browser": "netscape", "port": 9222})))
    assert reply["ok"] is False and "netscape" in reply["error"]
    assert cfg.get_state("active_browser") == "chrome", "a rejected save changes nothing"


def test_empty_per_browser_fields_never_erase_the_stored_ones(cfg):
    host, _ = _host(cfg)
    host.set_cdp_config(json.dumps({"browser": "firefox", "port": 9222,
                                    "browsers": {"firefox": {"user_data_dir": "", "extra_args": ""}}}))
    assert cfg.get_state("cdp_browsers")["firefox"]["user_data_dir"] == br.default_data_dir("firefox")
    assert cfg.get_state("cdp_browsers")["firefox"]["extra_args"] == "-no-remote"


# ── the launch command slot ──


def test_get_chrome_launch_command_follows_the_active_browser(cfg):
    host, _ = _host(cfg)
    host.set_cdp_config(json.dumps({"browser": "firefox", "port": 9222, "url_pattern": "arena.ai"}))
    launch = json.loads(host.get_chrome_launch_command())
    assert launch["browser"] == "firefox" and launch["protocol"] == "rdp"
    assert launch["resolved_port"] == 9223
    assert "firefox" in launch["windows"] and "--profile=" in launch["windows"]
    assert launch["macos"] and launch["linux_with_url"]
    assert launch["test_url"] == "tcp://127.0.0.1:9223"
    assert "screenshot" in launch["unavailable"]
    assert launch["url_pattern"] == "arena.ai"


def test_the_shared_port_stays_one_setting_for_both_browsers(cfg):
    host, _ = _host(cfg)
    payload = json.loads(host.get_cdp_config())
    assert len({b["dir_flag"] for b in payload["browsers"]}) > 1
    assert len(payload["browsers"]) >= 2
    host.set_cdp_config(json.dumps({"browser": "chrome", "port": 9229}))
    after = json.loads(host.get_cdp_config())
    assert (after["port"], after["browsers"][1]["resolved_port"]) == (9229, 9230), \
        "one base port, per-browser endpoints"


def test_browser_support_added_payloads_not_bridge_slots():
    from tests.test_bridge_slots import FROZEN_SLOTS

    assert len(FROZEN_SLOTS) == 137, "the frozen slot table is untouched by this round"
    for slot in ("get_cdp_config", "set_cdp_config", "get_chrome_launch_command"):
        assert slot in FROZEN_SLOTS
    assert not (FROZEN_SLOTS & {"get_browser_config", "set_browser_config", "list_browsers",
                                "get_browser_launch_command"}), "browser support rides the CDP slots"
