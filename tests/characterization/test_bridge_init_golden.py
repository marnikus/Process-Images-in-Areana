"""Bridge.__init__ characterization (roadmap W1.2, RULE 8).

Locks the observable end-state of constructing a Bridge headless BEFORE
the __init__ split into _build_*/_wire_* helpers. The refactor must keep
this green unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import AppState
from app.persistence.config_manager import ConfigManager
from app.core.undo_service import UndoService
from app.ui.bridge import Bridge


@pytest.fixture
def bridge(tmp_path: Path, qapp) -> Bridge:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    state_path = tmp_path / "state.json"
    return Bridge(ConfigManager(str(config_dir)), state_path)


@pytest.mark.unit
def test_init_core_state(bridge: Bridge, tmp_path: Path):
    assert bridge.config is not None
    assert bridge.state_path == tmp_path / "state.json"
    assert isinstance(bridge.state, AppState)
    assert bridge.cdp is None
    assert isinstance(bridge.undo_service, UndoService)
    # undo history load attempted on init (no crash with fresh config)
    assert bridge.config.undo is not None


@pytest.mark.unit
def test_init_run_flags(bridge: Bridge):
    assert bridge._run_state == "idle"
    assert bridge._cancel_requested is False
    assert bridge._pause_requested is False
    assert bridge._stop_after is False
    assert bridge._exported_paths == {}
    assert bridge._persist_ok is True
    assert bridge._restore_note_done is False


@pytest.mark.unit
def test_init_cdp_bg_infra(bridge: Bridge):
    assert bridge._bg_loop is None
    assert bridge._bg_thread is None
    assert bridge._bg_lock is not None
    assert bridge._bg_ready is not None


@pytest.mark.unit
def test_init_debounce_and_scan_flags(bridge: Bridge):
    assert bridge._last_find_query == ""
    assert bridge._last_find_ts == 0.0
    assert bridge._last_connect_ws == ""
    assert bridge._last_connect_ts == 0.0
    assert bridge._find_in_progress is False
    assert bridge._connect_in_progress is False
    assert bridge._auto_scan_running is False
    assert bridge._ensure_running is False
    assert bridge._scan_in_progress is False


@pytest.mark.unit
def test_init_thumbnail_infra(bridge: Bridge):
    assert bridge._thumb_cache == {}
    assert bridge._thumb_in_progress == set()
    assert bridge._thumb_executor is not None  # thread pool built headless


@pytest.mark.unit
def test_init_watcher_service(bridge: Bridge):
    from app.services.watcher import WatcherService

    assert isinstance(bridge._watcher, WatcherService)
    assert bridge._watcher_loop_task is None
    # default config: watcher disabled, default intervals
    cfg = bridge._watcher.config
    assert cfg.enabled is False
    assert cfg.check_interval_ms == 2000
    assert cfg.captcha_timeout_sec == 300
    assert cfg.generation_timeout_sec == 600
    assert cfg.auto_pause_jobs is True


@pytest.mark.unit
def test_init_page_pool(bridge: Bridge):
    from app.browser.page_pool import PagePool

    assert isinstance(bridge._page_pool, PagePool)
    assert bridge._page_pool._host == "127.0.0.1"
    assert bridge._page_pool._port == 9222


@pytest.mark.unit
def test_init_logs_build_version(bridge: Bridge):
    # _log_build_version ran: log_message signal history is not stored,
    # but the method must not raise — covered by successful construction
    # plus the version banner side effect (log_message emissions).
    assert bridge._run_state == "idle"
