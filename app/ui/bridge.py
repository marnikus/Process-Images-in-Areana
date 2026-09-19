"""Bridge — QWebChannel QObject exposing slots to JS.

Handles:
- layout persistence (grid_layout, window_states)
- theme
- window presets (save/load/list/delete/import/export with preview)
- arena operations (urls, folder, queue, prompt, settings, run controls, highlight)
"""

import asyncio
import json
import logging
from pathlib import Path

from app.ui.qt_compat import QObject, Signal, Slot

from app.core.layout_service import (
    canonical_grid_payload, default_payload,
)
from app.core.models import AppState
from app.core.persistence import load_state
from app.core.scanner import scan_folder
from app.persistence.config_manager import ConfigManager
from app.core.undo_service import UndoService
from app.ui.panels import blocks_stack, layout_state
from app.ui.panels.watcher_captcha import (
    captcha_service, get_watcher_cdp_controller, on_watcher_state)
from app.services.run_state import persist_cooldowns
from app.ui.panels.url_queue import (
    _add_missing_rows,
    _checked_tabs_ready,
    _dedupe_state_rows,
    _tab_already_owned,
    _urls_gate_error,
)  # compat: single source lives in panels/url_queue.py
from app.ui.panels.layout_state import LayoutStateMixin
from app.ui.panels.blocks_library import BlocksLibraryMixin
from app.ui.panels.blocks_stack import BlocksStackMixin
from app.ui.panels.undo_history import UndoHistoryMixin
from app.ui.panels.url_queue import UrlQueueMixin
from app.ui.panels.queue_scan import QueueScanMixin
from app.ui.panels.app_settings import AppSettingsMixin
from app.ui.panels.watcher_captcha import WatcherCaptchaMixin
from app.ui.panels.page_pool import PagePoolMixin
from app.ui.panels.browser_tabs import BrowserTabsMixin
from app.ui.panels.cdp_tools import CdpToolsMixin
from app.ui.panels.run_control import RunControlMixin, emit_job_action_status
from app.ui.services import arena_serialize, undo_entries
from app.core.action_blocks import (
    default_stack,
    stack_to_dicts,
)

log = logging.getLogger("arena")


# ── URL-row ownership helpers (I-33) — module level, keep Bridge slim ──








class Bridge(QObject, LayoutStateMixin, BlocksLibraryMixin, BlocksStackMixin, UndoHistoryMixin, UrlQueueMixin, QueueScanMixin, AppSettingsMixin, WatcherCaptchaMixin, PagePoolMixin, BrowserTabsMixin, CdpToolsMixin, RunControlMixin):
    log_message = Signal(str, str)
    grid_layout_changed = Signal(str)
    grid_layout_persisted = Signal(bool)
    window_preset_list_updated = Signal(str)
    arena_log = Signal(str, str)
    arena_state_updated = Signal(str)
    progress_updated = Signal(str)
    highlight_rect = Signal(str)
    history_changed = Signal()
    undo_state_changed = Signal(str)  # JSON {history,index,canUndo,canRedo}
    tabs_received = Signal(str)
    connection_status = Signal(str)
    tab_match_result = Signal(str, str)
    url_presets_updated = Signal(str)
    presets_changed = Signal(str, str)  # kind, payload
    action_blocks_updated = Signal(str)  # JSON array of blocks
    job_action_status = Signal(str, str, str)  # jobId, blockId, statusJson
    job_started = Signal(str, str)  # jobId, imagePath
    job_finished = Signal(str, str)  # jobId, resultJson
    watcher_status = Signal(str)  # JSON status
    watcher_log = Signal(str, str)  # msg, level
    page_pool_updated = Signal(str)  # JSON snapshot steady/busy
    thumbnail_ready = Signal(str, str)  # img_id, payload_json — non-blocking thumb

    def __init__(self, config_manager: ConfigManager, state_path: Path, cdp_client=None, parent=None):
        super().__init__(parent)
        self.config = config_manager
        self.state_path = Path(state_path)
        self.state = load_state(self.state_path)
        self._run_state = "idle"
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self._exported_paths = {}
        self.undo_service = UndoService(self.config.undo)
        self.cdp = cdp_client
        # persistent bg loop for CDP (keeps websocket alive)
        import threading as _th
        self._bg_loop = None
        self._bg_thread = None
        self._bg_lock = _th.Lock()
        self._bg_ready = _th.Event()
        # debouncing for CDP tab find/connect to avoid x2 logs and race
        self._last_find_query = ""
        self._last_find_ts = 0.0
        self._last_connect_ws = ""
        self._last_connect_ts = 0.0
        self._find_in_progress = False
        self._connect_in_progress = False
        self._auto_scan_running = False
        self._ensure_running = False
        self._persist_ok = True
        self._restore_note_done = False
        # thumbnail cache + thread pool to avoid UI freeze on mouse clicks
        # Previously get_image_thumbnail did PIL thumbnail sync in main thread for 80 images -> freeze
        self._thumb_cache = {}
        self._thumb_in_progress = set()
        try:
            import concurrent.futures as _cf
            self._thumb_executor = _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb")
        except Exception:
            self._thumb_executor = None
        # scan folder debouncing to avoid freeze
        self._scan_in_progress = False
        # ensure undo history loaded
        try:
            self.config.undo.load()
        except Exception:
            pass
        # install CDP status forwarding if client exists
        if self.cdp:
            try:
                self.cdp.connected.connect(lambda: self.connection_status.emit("connected"))
                self.cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
                self.cdp.error.connect(lambda e: self._on_cdp_error(e))
            except Exception:
                pass

        # Watcher service — passive recheck every x ms for generating icon or captcha
        self._watcher = None
        self._watcher_loop_task = None
        try:
            from app.services.watcher import WatcherService, WatcherConfig
            cfg = WatcherConfig(
                enabled=bool(self.config.get_state("watcher_enabled", False)),
                check_interval_ms=int(self.config.get_state("watcher_interval_ms", 2000)),
                captcha_timeout_sec=int(self.config.get_state("watcher_captcha_timeout_sec", 300)),
                generation_timeout_sec=int(self.config.get_state("watcher_generation_timeout_sec", 600)),
                auto_pause_jobs=bool(self.config.get_state("watcher_auto_pause", True)),
            )
            self._watcher = WatcherService(
                config=cfg,
                cdp_controller_getter=lambda: get_watcher_cdp_controller(self),
                job_runner_getter=lambda: self,
                logger=lambda msg, level="info": self._log(f"[Watcher] {msg}", level)
            )
            # Callback to emit watcher_status to UI
            def _watcher_cb(payload):
                try:
                    import json as _json
                    self.watcher_status.emit(_json.dumps(payload, ensure_ascii=False))
                except Exception:
                    pass
            # Use sync callback that will be called from async loop — need to handle via signal
            # We'll wrap to emit via log as well
            self._watcher.add_callback(lambda p: on_watcher_state(self, p))
            # Auto-start if enabled
            if cfg.enabled:
                # Start will be called when event loop is ready — schedule
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        self._watcher.start()
                    else:
                        # Will start on first get_watcher_config call or explicit start
                        pass
                except Exception:
                    pass
        except Exception as e:
            try:
                self._log(f"Watcher init failed: {e}", "warn")
            except Exception:
                pass
            self._watcher = None

        # PagePool — multi-page steady/busy tracking
        self._page_pool = None
        try:
            from app.browser.page_pool import PagePool
            self._page_pool = PagePool(logger=lambda m, l="info": self._log(m, l))
            try:
                host = self.config.get_state("cdp_host", "127.0.0.1")
                port = int(self.config.get_state("cdp_port", 9222))
            except Exception:
                host = "127.0.0.1"
                port = 9222
            self._page_pool._host = str(host)
            self._page_pool._port = int(port)
        except Exception as e:
            try:
                self._log(f"PagePool init failed: {e}", "warn")
            except Exception:
                pass
            self._page_pool = None
        self._log_build_version()

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

    def _emit_pool_status(self):
        try:
            if not self._page_pool:
                return
            snap = self._page_pool.status_snapshot()
            self.page_pool_updated.emit(json.dumps(snap, ensure_ascii=False))
            self._persist_cooldowns()
        except Exception:
            pass


    def _persist_cooldowns(self):
        # Contract §2: run_state owns cooldown persistence.
        return persist_cooldowns(self)

    def _on_cdp_error(self, err_msg: str):
        try:
            self._log(f"CDP error: {err_msg[:500]}", "error")
        except Exception:
            pass
        try:
            self.connection_status.emit("error")
        except Exception:
            pass

    # ---- Action Blocks — stacking jobs with visual confirmations ----
    def _get_action_blocks(self):
        return blocks_stack.get_action_blocks(self)

    def _emit_action_blocks(self):
        blocks_stack.emit_action_blocks(self)

    def _emit_job_action_status(self, action) -> None:
        # F8: runner seam (JobAction event); run_control owns the emit.
        emit_job_action_status(self, action)

    def _save_arena(self):
        layout_state.save_arena_state(self)

    def _emit_arena_state(self):
        layout_state.emit_arena_state(self)

    def _log(self, msg: str, level: str = "info"):
        # Emit only arena_log to avoid duplicate logs (previously emitted both log_message and arena_log
        # which JS connected both to LogConsole.log causing double lines)
        try:
            self.arena_log.emit(msg, level)
        except Exception:
            pass
        try:
            # Also try log_message but JS now dedupes? Keep only arena_log for single log
            # self.log_message.emit(msg, level)
            pass
        except Exception:
            pass

    # WebChannel constraint: slots must live on this QObject (wire format);
    # the lazy getter keeps __init__ untouched. Net line delta of this
    # change is negative (inline captcha blocks replaced by choke point).

    def _captcha_service(self):
        # Seam for main_window + app/services/captcha (watcher_captcha owns the factory).
        return captcha_service(self)
