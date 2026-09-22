"""Bridge — QWebChannel QObject exposing slots to JS.

Handles:
- layout persistence (grid_layout, window_states)
- theme
- window presets (save/load/list/delete/import/export with preview)
- arena operations (urls, folder, queue, prompt, settings, run controls, highlight)
"""

import json
import logging
from pathlib import Path

from app.ui.qt_compat import QObject, Signal

from app.core.persistence import load_state
from app.persistence.config_manager import ConfigManager
from app.ui.panels import blocks_stack, layout_state
from app.ui.panels.watcher_captcha import captcha_service
from app.services.run_state import persist_cooldowns
from app.ui.bridge_context import (
    build_context, init_run_state, init_tracking_state,
    log_build_version, wire_cdp)
from app.ui.panels.url_queue import (
    _add_missing_rows,
    _checked_tabs_ready,
    _dedupe_state_rows,
    _urls_gate_error,
)  # compat: single source lives in panels/url_queue.py
from app.ui.panels.layout_state import LayoutStateMixin
from app.ui.panels.blocks_library import BlocksLibraryMixin
from app.ui.panels.blocks_stack import BlocksStackMixin
from app.ui.panels.undo_history import UndoHistoryMixin
from app.ui.panels.url_queue import UrlQueueMixin
from app.ui.panels.queue_scan import QueueScanMixin
from app.ui.panels.app_settings import AppSettingsMixin
from app.ui.panels.job_history import JobHistoryMixin
from app.ui.panels.uivision import UiVisionMixin
from app.ui.panels.watcher_captcha import WatcherCaptchaMixin
from app.ui.panels.watcher_solver import WatcherSolverMixin
from app.ui.panels.page_pool import PagePoolMixin
from app.ui.panels.recording_sessions import RecordingSessionsMixin
from app.ui.panels.browser_tabs import BrowserTabsMixin
from app.ui.panels.cdp_tools import CdpToolsMixin
from app.ui.panels.run_control import RunControlMixin, emit_job_action_status

log = logging.getLogger("arena")


# ── URL-row ownership helpers (I-33) — module level, keep Bridge slim ──








class Bridge(QObject, LayoutStateMixin, BlocksLibraryMixin, BlocksStackMixin, UndoHistoryMixin, UrlQueueMixin, QueueScanMixin, AppSettingsMixin, WatcherCaptchaMixin, WatcherSolverMixin, PagePoolMixin, RecordingSessionsMixin, BrowserTabsMixin, CdpToolsMixin, RunControlMixin, JobHistoryMixin, UiVisionMixin):
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
    uivision_result = Signal(str)  # Ui.Vision macro verdict (arrives after polling)
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
    captcha_watcher_status = Signal(str)  # JSON: Captcha Watcher (SDK solver) counters
    page_pool_updated = Signal(str)  # JSON snapshot steady/busy
    thumbnail_ready = Signal(str, str)  # img_id, payload_json — non-blocking thumb
    job_history_updated = Signal(str)  # JSON {entries, limit, total, next_job_no}

    def __init__(self, config_manager: ConfigManager, state_path: Path, cdp_client=None, parent=None):
        super().__init__(parent)
        self.config = config_manager
        self.state_path = Path(state_path)
        self.state = load_state(self.state_path)
        self.cdp = cdp_client
        init_run_state(self)
        init_tracking_state(self)
        wire_cdp(self)
        ctx = build_context(self)
        self.undo_service = ctx.undo_service
        self._watcher = ctx.watcher
        self._page_pool = ctx.page_pool
        self._thumb_executor = ctx.thumb_executor
        log_build_version(self)

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

    # WebChannel constraint: slots live on this QObject (wire format); lazy getters keep __init__ slim.

    def _captcha_service(self):
        # Seam for main_window + app/services/captcha (watcher_captcha owns the factory).
        return captcha_service(self)
