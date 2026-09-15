import pytest
from app.services.watcher import WatcherConfig, WatcherState, WatcherService

def test_watcher_config_defaults():
    cfg = WatcherConfig()
    assert cfg.check_interval_ms == 2000
    assert cfg.captcha_timeout_sec == 300
    assert cfg.generation_timeout_sec == 600
    assert cfg.enabled is False

def test_watcher_state_defaults():
    st = WatcherState()
    assert st.status == "idle"
    assert st.checks_count == 0

def test_watcher_update_config():
    cfg = WatcherConfig()
    svc = WatcherService(config=cfg)
    svc.update_config(enabled=True, check_interval_ms=1500, captcha_timeout_sec=200, generation_timeout_sec=400)
    assert svc.config.enabled is True
    assert svc.config.check_interval_ms == 1500
    assert svc.config.captcha_timeout_sec == 200
    assert svc.config.generation_timeout_sec == 400
    # cleanup
    svc.stop()

def test_watcher_get_config():
    cfg = WatcherConfig(enabled=True, check_interval_ms=1000)
    svc = WatcherService(config=cfg)
    d = svc.get_config()
    assert d["enabled"] is True
    assert d["check_interval_ms"] == 1000

def test_watcher_get_state():
    svc = WatcherService()
    st = svc.get_state()
    assert "status" in st
    assert "checks_count" in st
