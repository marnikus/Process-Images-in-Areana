"""Unit tests — auto-connect settings: defaults, clamping, storage round-trip (spec 04)."""

from __future__ import annotations

import pytest

from app.browser.autoconnect_config import (
    DEFAULT_INTERVAL_MS,
    MAX_INTERVAL_MS,
    MIN_INTERVAL_MS,
    AutoConnectConfig,
    config_from_getter,
)
from app.persistence.config_manager import DEFAULT_SESSION


@pytest.mark.unit
def test_defaults_scan_localhost_and_match_arena():
    cfg = AutoConnectConfig()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9222
    assert cfg.endpoint == "127.0.0.1:9222"
    assert cfg.patterns == ["arena.ai"]
    assert cfg.enabled is True
    assert cfg.interval_ms == DEFAULT_INTERVAL_MS
    assert cfg.max_pages == 0


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    (10, MIN_INTERVAL_MS),
    (0, MIN_INTERVAL_MS),
    ("2500", 2500),
    (10**9, MAX_INTERVAL_MS),
    ("nonsense", DEFAULT_INTERVAL_MS),
    (None, DEFAULT_INTERVAL_MS),
])
def test_interval_is_clamped_to_a_sane_range(raw, expected):
    assert AutoConnectConfig(interval_ms=raw).interval_ms == expected


@pytest.mark.unit
def test_port_and_pattern_are_normalized():
    cfg = AutoConnectConfig(host="  ", port="9223", url_pattern="  HTTPS://Arena.AI/ ", max_pages="-3")
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9223
    assert cfg.patterns == ["arena.ai"]
    assert cfg.max_pages == 0


@pytest.mark.unit
def test_to_dict_carries_every_storable_field():
    cfg = AutoConnectConfig(enabled=False, url_pattern="arena.ai, lmarena.ai", interval_ms=2000,
                            max_pages=4, connect_primary=False, host="10.0.0.5", port=9223)
    assert cfg.to_dict() == {
        "enabled": False,
        "url_pattern": "arena.ai, lmarena.ai",
        "patterns": ["arena.ai", "lmarena.ai"],
        "interval_ms": 2000,
        "max_pages": 4,
        "connect_primary": False,
        "host": "10.0.0.5",
        "port": 9223,
        "endpoint": "10.0.0.5:9223",
    }


@pytest.mark.unit
def test_config_from_getter_reads_settings_store():
    store = {
        "autoconnect_enabled": False,
        "autoconnect_url_pattern": "arena.ai/c",
        "autoconnect_interval_ms": 3000,
        "autoconnect_max_pages": 2,
        "autoconnect_primary": False,
        "cdp_host": "127.0.0.1",
        "cdp_port": 9223,
    }
    cfg = config_from_getter(lambda key, default=None: store.get(key, default))
    assert cfg.enabled is False
    assert cfg.patterns == ["arena.ai/c"]
    assert cfg.interval_ms == 3000
    assert cfg.max_pages == 2
    assert cfg.connect_primary is False
    assert cfg.endpoint == "127.0.0.1:9223"


@pytest.mark.unit
def test_config_from_getter_falls_back_on_missing_or_bad_values():
    cfg = config_from_getter(lambda _key, default=None: default)
    assert cfg.enabled is True
    assert cfg.patterns == ["arena.ai"]
    assert cfg.port == 9222
    broken = config_from_getter(lambda key, default=None: "abc" if "interval" in key or "port" in key else default)
    assert broken.interval_ms == DEFAULT_INTERVAL_MS
    assert broken.port == 9222


@pytest.mark.unit
def test_session_defaults_persist_the_autoconnect_fields(tmp_path):
    from app.persistence.config_manager import ConfigManager

    for key in ("autoconnect_enabled", "autoconnect_url_pattern", "autoconnect_interval_ms",
                "autoconnect_max_pages", "autoconnect_primary"):
        assert key in DEFAULT_SESSION
    cm = ConfigManager(config_dir=str(tmp_path))
    assert cm.get_state("autoconnect_url_pattern") == "arena.ai"
    cm.set_state(autoconnect_url_pattern="lmarena.ai", autoconnect_interval_ms=2500)
    reloaded = ConfigManager(config_dir=str(tmp_path))
    assert reloaded.get_state("autoconnect_url_pattern") == "lmarena.ai"
    assert reloaded.get_state("autoconnect_interval_ms") == 2500
    cfg = config_from_getter(reloaded.get_state)
    assert cfg.patterns == ["lmarena.ai"]
    assert cfg.interval_ms == 2500
