"""I-79 — the "Start new chat as new tab" setting: defaults, URL cleaning, cooldown slots."""
from __future__ import annotations

import json

import pytest

from app.browser.page_pool import PagePool
from app.persistence.config_manager import ConfigManager
from app.services import new_tab_setting
from app.ui.panels.page_pool import PagePoolMixin
from tests.test_panel_slots import make_host


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


@pytest.mark.parametrize("raw, want", [
    ("https://arena.ai/image/direct?model_a=max", "https://arena.ai/image/direct?model_a=max"),
    ("  http://localhost:3000/new  ", "http://localhost:3000/new"),
    ("", new_tab_setting.DEFAULT_URL), (None, new_tab_setting.DEFAULT_URL), ("javascript:alert(1)", new_tab_setting.DEFAULT_URL),
    ("arena.ai/image", new_tab_setting.DEFAULT_URL), ("https://", new_tab_setting.DEFAULT_URL),
])
def test_clean_url_keeps_http_urls_and_heals_the_rest(raw, want):
    assert new_tab_setting.clean_url(raw) == want


def test_a_fresh_session_has_the_option_off_with_the_arena_default(cfg):
    assert new_tab_setting.read_setting(cfg.get_state) == {"enabled": False, "url": "https://arena.ai/image/direct?model_a=max"}
    assert new_tab_setting.wanted_url(type("B", (), {"config": cfg})()) == ""


def test_an_unreadable_session_is_off():
    def broken(key, default=None):
        raise RuntimeError("disk")
    assert new_tab_setting.read_setting(broken)["enabled"] is False


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
    assert new_tab_setting.wanted_url(type("B", (), {"config": cfg})()) == "https://arena.ai/image/direct"


def test_a_bad_url_heals_to_the_default(cfg):
    host = _host(cfg)
    host.set_cooldown_config(json.dumps({"new_tab": True, "new_tab_url": "ftp://x"}))
    assert json.loads(host.get_cooldown_config())["new_tab"]["url"] == new_tab_setting.DEFAULT_URL


def test_the_url_list_save_keeps_the_new_tab_option(cfg):
    """The URL List bar sends only its four values — it must not switch the option off."""
    host = _host(cfg)
    host.set_cooldown_config(json.dumps({"new_tab": True, "new_tab_url": "https://arena.ai/image/direct"}))
    host.set_cooldown_config(json.dumps({"enabled": True, "min_seconds": 120, "captcha_penalty_seconds": 60,
                                         "rate_limit_penalty_seconds": 600}))
    loaded = json.loads(host.get_cooldown_config())
    assert loaded["new_tab"] == {"enabled": True, "url": "https://arena.ai/image/direct"}
    assert loaded["config"]["min_seconds"] == 120


def test_the_settings_save_keeps_the_url_list_pause_values(cfg):
    """Settings sends only the option — pause, captcha and rate-limit values stay as the URL List set them."""
    host = _host(cfg)
    host.set_cooldown_config(json.dumps({"enabled": False, "min_seconds": 120, "captcha_penalty_seconds": 60,
                                         "rate_limit_penalty_seconds": 600}))
    reply = json.loads(host.set_cooldown_config(json.dumps({"new_tab": True, "new_tab_url": ""})))
    assert reply["ok"] and reply["new_tab"] == {"enabled": True, "url": new_tab_setting.DEFAULT_URL}
    config = reply["config"]
    assert (config["enabled"], config["min_seconds"], config["captcha_penalty_seconds"],
            config["rate_limit_penalty_seconds"]) == (False, 120, 60, 600)


def test_the_seeded_default_and_the_healing_default_are_one_url():
    """Audit #4 N3. The literal lived in two files: `config_manager` seeds the
    config file, `new_tab_setting` heals a bad value. Changing one made the
    other win silently, depending on which read path ran. The persistence
    layer must take the leaf's constant, not repeat it."""
    from app.persistence import config_manager
    assert config_manager.DEFAULT_SESSION[new_tab_setting.URL_KEY] == new_tab_setting.DEFAULT_URL
