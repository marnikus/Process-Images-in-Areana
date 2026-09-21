"""Bridge construction context — heavy/fallible init pieces (A6).

`Bridge.__init__` stays an orchestrator (≤20 LOC): plain config/state
inline, flags + services built here. All attrs identical to the pre-A6
inline version, plus `_batch_future = None` (was lazily created).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import threading

from app.core.undo_service import UndoService
from app.services.live.bus import LiveBus
from app.ui.panels.queue_scan import push_queue_undo
from app.ui.panels.watcher_captcha import (
    get_watcher_cdp_controller, on_watcher_state)


@dataclass
class BridgeContext:
    """Constructed services for a Bridge (None where init failed)."""

    undo_service: Any
    watcher: Any
    page_pool: Any
    thumb_executor: Any


def init_run_state(bridge) -> None:
    """Run-lifecycle flags + per-run stores + the live bus / queue lock (S4)."""
    bridge._run_state = "idle"
    bridge._cancel_requested = False
    bridge._pause_requested = False
    bridge._stop_after = False
    bridge._batch_future = None
    bridge._exported_paths = {}
    bridge._live_bus = LiveBus()
    bridge._state_lock = threading.RLock()
    bridge._push_queue_undo = lambda: push_queue_undo(bridge)  # the funnel's undo seam (services stay ui-free)


def init_tracking_state(bridge) -> None:
    """Bg-loop handles, CDP debounce/progress trackers, misc flags."""
    import threading as _th
    bridge._bg_loop = None
    bridge._bg_thread = None
    bridge._bg_lock = _th.Lock()
    bridge._bg_ready = _th.Event()
    bridge._watcher_loop_task = None
    bridge._last_find_query = ""
    bridge._last_find_ts = 0.0
    bridge._last_connect_ws = ""
    bridge._last_connect_ts = 0.0
    bridge._find_in_progress = False
    bridge._connect_in_progress = False
    bridge._auto_scan_running = False
    bridge._ensure_running = False
    bridge._persist_ok = True
    bridge._restore_note_done = False
    bridge._scan_in_progress = False


def wire_cdp(bridge) -> None:
    """Forward client connected/disconnected/error to bridge signals."""
    if not bridge.cdp:
        return
    try:
        bridge.cdp.connected.connect(
            lambda: bridge.connection_status.emit("connected"))
        bridge.cdp.disconnected.connect(
            lambda: bridge.connection_status.emit("disconnected"))
        bridge.cdp.error.connect(lambda e: on_cdp_error(bridge, e))
    except Exception:
        pass


def on_cdp_error(bridge, err_msg: str) -> None:
    """Log a CDP error and flag the connection status."""
    try:
        bridge._log(f"CDP error: {err_msg[:500]}", "error")
    except Exception:
        pass
    try:
        bridge.connection_status.emit("error")
    except Exception:
        pass


def log_build_version(bridge) -> None:
    """Log the running commit so behavior is traceable. Best effort."""
    try:
        import subprocess
        here = Path(__file__).resolve().parents[2]
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True,
                             cwd=here, timeout=5).stdout.strip()
        if sha:
            bridge._log(f"📌 Build {sha}", "info")
    except Exception:
        pass


def _log_quiet(bridge, msg: str, level: str = "warn") -> None:
    """Best-effort construction log (never breaks init)."""
    try:
        bridge._log(msg, level)
    except Exception:
        pass


def _watcher_config(bridge):
    """WatcherConfig from stored watcher_* settings."""
    from app.services.watcher import WatcherConfig
    return WatcherConfig(
        enabled=bool(bridge.config.get_state("watcher_enabled", False)),
        check_interval_ms=int(bridge.config.get_state("watcher_interval_ms", 2000)),
        captcha_timeout_sec=int(bridge.config.get_state("watcher_captcha_timeout_sec", 300)),
        generation_timeout_sec=int(bridge.config.get_state("watcher_generation_timeout_sec", 600)),
        auto_pause_jobs=bool(bridge.config.get_state("watcher_auto_pause", True)),
    )


def _activate_watcher(bridge, watcher) -> None:
    """State callback + autostart when the watcher is enabled."""
    watcher.add_callback(lambda p: on_watcher_state(bridge, p))
    if not getattr(watcher.config, "enabled", False):
        return
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            watcher.start()
    except Exception:
        pass


def wire_watcher(bridge):
    """Watcher service (autostarted when enabled); None on failure."""
    try:
        from app.services.watcher import WatcherService
        watcher = WatcherService(
            config=_watcher_config(bridge),
            cdp_controller_getter=lambda: get_watcher_cdp_controller(bridge),
            job_runner_getter=lambda: bridge,
            logger=lambda msg, level="info": bridge._log(f"[Watcher] {msg}", level),
        )
        _activate_watcher(bridge, watcher)
        return watcher
    except Exception as e:
        _log_quiet(bridge, f"Watcher init failed: {e}")
        return None


def _pool_endpoint(bridge) -> tuple:
    """(host, port) for pool tagging; safe defaults."""
    try:
        host = bridge.config.get_state("cdp_host", "127.0.0.1")
        port = int(bridge.config.get_state("cdp_port", 9222))
    except Exception:
        host = "127.0.0.1"
        port = 9222
    return host, port


def _alias_book(bridge):
    """The persisted readable-id registry (D-6); an empty book on any failure."""
    from app.core.tab_alias import AliasBook
    from app.persistence.cooldown_store import load_aliases
    from app.services.run_state import cooldowns_path
    try:
        return AliasBook(load_aliases(cooldowns_path(bridge)))
    except Exception:
        return AliasBook()


def wire_page_pool(bridge):
    """PagePool tagged with host/port + the saved numbers; None on any failure."""
    try:
        from app.browser.page_pool import PagePool
        pool = PagePool(logger=lambda m, l="info": bridge._log(m, l),
                        alias_book=_alias_book(bridge))
        host, port = _pool_endpoint(bridge)
        pool._host = str(host)
        pool._port = int(port)
        return pool
    except Exception as e:
        _log_quiet(bridge, f"PagePool init failed: {e}")
        return None


def wire_thumb(bridge):
    """Thumb cache + pool (off-thread, avoids UI freeze); None on failure."""
    bridge._thumb_cache = {}
    bridge._thumb_in_progress = set()
    try:
        import concurrent.futures as _cf
        return _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb")
    except Exception:
        return None


def build_context(bridge) -> BridgeContext:
    """Fallible services (undo/watcher/pool/thumb) in one bundle."""
    try:
        bridge.config.undo.load()
    except Exception:
        pass
    return BridgeContext(
        undo_service=UndoService(bridge.config.undo),
        watcher=wire_watcher(bridge),
        page_pool=wire_page_pool(bridge),
        thumb_executor=wire_thumb(bridge),
    )
