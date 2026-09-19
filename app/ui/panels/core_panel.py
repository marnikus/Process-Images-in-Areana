"""Core Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import asyncio
from pathlib import Path
try:
    from PySide6.QtCore import QObject, Signal, Slot
    _qt_core = True
except ImportError:
    _qt_core = False

if not _qt_core:  # headless shim (no PySide6) — exercised by tests/test_qt_shim_fallback.py
    class QObject:
        def __init__(self, *qt_shim_args, **qt_shim_kwargs): pass

    def Signal(*sig_shim_args, **sig_shim_kwargs):
        class _Sig:
            def emit(self, *emit_shim_args, **emit_shim_kwargs): pass
            def connect(self, *connect_shim_args, **connect_shim_kwargs): pass
        return _Sig()

    def Slot(*slot_shim_args, **slot_shim_kwargs):
        def deco(fn): return fn
        return deco

try:
    from PySide6.QtWidgets import QFileDialog
except ImportError:
    QFileDialog = None




class BridgeCore:

    def _init_state_flags(self) -> None:
        """Construction defaults: run lifecycle, CDP bg loop, debounce guards."""
        self._run_state = "idle"
        self._cancel_requested = self._pause_requested = False
        self._stop_after = False
        self._exported_paths = {}
        self._persist_ok = True
        self._restore_note_done = False
        import threading as _th  # bg CDP loop keeps websocket alive
        self._bg_loop = self._bg_thread = None
        self._bg_lock = _th.Lock()
        self._bg_ready = _th.Event()
        # find/connect debounce avoids x2 logs and races
        self._last_find_query = self._last_connect_ws = ""
        self._last_find_ts = self._last_connect_ts = 0.0
        self._find_in_progress = self._connect_in_progress = False
        self._auto_scan_running = self._ensure_running = False
        self._scan_in_progress = False

    def _init_thumbnail_infra(self) -> None:
        """Thumb cache + pool — PIL thumbnails off the main thread (80-img freeze)."""
        self._thumb_cache = {}
        self._thumb_in_progress = set()
        try:
            import concurrent.futures as _cf
            self._thumb_executor = _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb")
        except Exception:
            self._thumb_executor = None

    def _wire_cdp_client(self) -> None:
        """Install CDP status forwarding signals if a client exists."""
        if not self.cdp:
            return
        try:
            self.cdp.connected.connect(lambda: self.connection_status.emit("connected"))
            self.cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
            self.cdp.error.connect(lambda e: self._on_cdp_error(e))
        except Exception:
            pass

    def _build_watcher_service(self):
        """Watcher service — passive recheck every x ms for generating icon
        or captcha. Returns the service, or None on init failure."""
        try:
            from app.services.watcher import WatcherService
            cfg = self._build_watcher_config()
            self._watcher = WatcherService(
                config=cfg,
                cdp_controller_getter=lambda: self._get_watcher_cdp_controller(),
                job_runner_getter=lambda: self,
                logger=lambda msg, level="info": self._log(f"[Watcher] {msg}", level)
            )
            self._watcher.add_callback(lambda p: self._on_watcher_state(p))
            if cfg.enabled:  # auto-start only when a loop is already running
                try:
                    import asyncio
                    if asyncio.get_event_loop().is_running():
                        self._watcher.start()
                except Exception:
                    pass
            return self._watcher
        except Exception as e:
            try:
                self._log(f"Watcher init failed: {e}", "warn")
            except Exception:
                pass
            return None

    def _build_watcher_config(self):
        """Watcher settings from user config (intervals, timeouts, pause)."""
        from app.services.watcher import WatcherConfig

        return WatcherConfig(
            enabled=bool(self.config.get_state("watcher_enabled", False)),
            check_interval_ms=int(self.config.get_state("watcher_interval_ms", 2000)),
            captcha_timeout_sec=int(self.config.get_state("watcher_captcha_timeout_sec", 300)),
            generation_timeout_sec=int(self.config.get_state("watcher_generation_timeout_sec", 600)),
            auto_pause_jobs=bool(self.config.get_state("watcher_auto_pause", True)),
        )

    def _build_page_pool(self):
        """PagePool — multi-page steady/busy tracking bound to CDP host/port."""
        try:
            from app.browser.page_pool import PagePool
            pool = PagePool(logger=lambda m, l="info": self._log(m, l))
            try:
                host = self.config.get_state("cdp_host", "127.0.0.1")
                port = int(self.config.get_state("cdp_port", 9222))
            except Exception:
                host, port = "127.0.0.1", 9222
            pool._host = str(host)
            pool._port = int(port)
            return pool
        except Exception as e:
            try:
                self._log(f"PagePool init failed: {e}", "warn")
            except Exception:
                pass
            return None

    def _log_build_version(self) -> None:
        """Log the running commit so behavior is traceable. Best effort."""
        try:
            import subprocess
            here = Path(__file__).resolve().parents[2]
            sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=here, timeout=5).stdout.strip()
            if sha:
                self._log(f"📌 Build {sha}", "info")
        except Exception:
            pass
