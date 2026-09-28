"""I-79 — the "Start new chat as new tab" setting: defaults, URL cleaning, cooldown slots."""
from __future__ import annotations

import json

import pytest

from app.browser.page_pool import PagePool
from app.persistence.config_manager import ConfigManager
from app.services import new_tab
from app.ui.panels.page_pool import PagePoolMixin
from tests.test_panel_slots import make_host


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


@pytest.mark.parametrize("raw, want", [
    ("https://arena.ai/image/direct?model_a=max", "https://arena.ai/image/direct?model_a=max"),
    ("  http://localhost:3000/new  ", "http://localhost:3000/new"),
    ("", new_tab.DEFAULT_URL), (None, new_tab.DEFAULT_URL), ("javascript:alert(1)", new_tab.DEFAULT_URL),
    ("arena.ai/image", new_tab.DEFAULT_URL), ("https://", new_tab.DEFAULT_URL),
])
def test_clean_url_keeps_http_urls_and_heals_the_rest(raw, want):
    assert new_tab.clean_url(raw) == want


def test_a_fresh_session_has_the_option_off_with_the_arena_default(cfg):
    assert new_tab.read_setting(cfg.get_state) == {"enabled": False, "url": "https://arena.ai/image/direct?model_a=max"}
    assert new_tab.wanted_url(type("B", (), {"config": cfg})()) == ""


def test_an_unreadable_session_is_off():
    def broken(key, default=None):
        raise RuntimeError("disk")
    assert new_tab.read_setting(broken)["enabled"] is False


def _host(cfg):
    host, _ = make_host((PagePoolMixin,), _page_pool=PagePool(), config=cfg, _log=lambda m, l="info": None,
                        _emit_pool_status=lambda: None, _persist_cooldowns=lambda: None)
    return host


def test_the_cooldown_slots_save_and_load_the_option(cfg):
    host = _host(cfg)
    reply = json.loads(host.set_cooldown_config(json.dumps(
        {"enabled": True, "min_seconds": 60, "new_tab": True, "new_tab_url": "https://arena.ai/image/direct"})))
    assert reply["ok"] and reply["new_tab"] == {"enabled": True, "url": "https://arena.ai/image/direct"}
    loaded = json.loads(host.get_cooldown_config())
    assert loaded["new_tab"] == {"enabled": True, "url": "https://arena.ai/image/direct"}
    assert new_tab.wanted_url(type("B", (), {"config": cfg})()) == "https://arena.ai/image/direct"


def test_an_old_payload_without_the_keys_turns_the_option_off(cfg):
    host = _host(cfg)
    json.loads(host.set_cooldown_config(json.dumps({"new_tab": True, "new_tab_url": "ftp://x"})))
    assert json.loads(host.get_cooldown_config())["new_tab"]["url"] == new_tab.DEFAULT_URL
    json.loads(host.set_cooldown_config(json.dumps({"enabled": True})))
    assert json.loads(host.get_cooldown_config())["new_tab"]["enabled"] is False
