"""Tests for C9 split watcher services — config, jobs, overlay pure helpers."""
import time
import pytest
from app.services.watcher_config import WatcherConfig, WatcherState
from app.services.watcher_jobs import pause_jobs, resume_jobs
from app.services.watcher_overlay import (
    build_captcha_msg, build_generation_msg, should_start_captcha_waiting,
    should_start_generation_waiting, is_captcha_timeout, is_generation_timeout,
    should_clear_overlay, build_clear_msg
)

def test_watcher_config_defaults():
    cfg = WatcherConfig()
    assert cfg.check_interval_ms == 2000
    assert cfg.captcha_timeout_sec == 300

def test_watcher_state_to_dict():
    st = WatcherState(status="idle", checks_count=1)
    d = st.to_dict()
    assert d["status"] == "idle"
    assert d["checks_count"] == 1

def test_pause_resume_no_runner():
    cfg = WatcherConfig(enabled=True, auto_pause_jobs=True)
    pause_jobs(cfg, None)  # should not crash
    resume_jobs(cfg, None)

def test_pause_resume_with_runner():
    class FakeRunner:
        paused = False
        resumed = False
        def pause_run(self): self.paused = True
        def resume_run(self): self.resumed = True
    cfg = WatcherConfig(auto_pause_jobs=True)
    fr = FakeRunner()
    pause_jobs(cfg, lambda: fr)
    assert fr.paused
    resume_jobs(cfg, lambda: fr)
    assert fr.resumed

def test_pause_resume_disabled():
    class FakeRunner:
        def pause_run(self): raise AssertionError("should not be called")
    cfg = WatcherConfig(auto_pause_jobs=False)
    pause_jobs(cfg, lambda: FakeRunner())  # no call

def test_overlay_builders():
    assert "Captcha" in build_captcha_msg(10) or "captcha" in build_captcha_msg(10).lower()
    assert "generation" in build_generation_msg({"details": []}, 5).lower()
    assert "generating" in build_generation_msg({}, 5)

def test_should_start():
    assert should_start_captcha_waiting(None)
    assert not should_start_captcha_waiting("captcha")
    assert should_start_generation_waiting(None)
    assert not should_start_generation_waiting("generation")

def test_timeouts():
    now = time.time()
    assert not is_captcha_timeout(None, 10)
    assert is_captcha_timeout(now - 20, 10)
    assert not is_captcha_timeout(now, 10)
    assert not is_generation_timeout(None, 10)
    assert is_generation_timeout(now - 20, 10)

def test_should_clear():
    assert should_clear_overlay("generation", False, False)
    assert not should_clear_overlay("generation", True, False)
    assert not should_clear_overlay("idle", False, False)

def test_build_clear_msg():
    assert "finished" in build_clear_msg("captcha", 5)
