"""Bridge — QWebChannel facade (W1.6).

Signals + composition root only: behaviour lives in the app/ui/panels/*
mixins (LCOM4 clusters). PySide6 registers @Slot methods from plain
mixins into the metaobject (verified by tests/test_bridge_slots.py and
the mixin metaobject test), so the JS surface is unchanged.
"""

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

from app.core.persistence import load_state
from app.persistence.config_manager import ConfigManager
from app.core.undo_service import UndoService


from app.ui.panels.core_panel import BridgeCore
from app.ui.panels.arena_state_panel import ArenaStatePanel
from app.ui.panels.action_status_panel import JobStatusPanel
from app.ui.panels.blocks_panel import ActionBlocksPanel, StackPresetsPanel, ActionBlocksIoPanel
from app.ui.panels.undo_panel import UndoEditPanel, UndoApplyPanel, UndoApiPanel
from app.ui.panels.grid_layout_panel import GridLayoutPanel
from app.ui.panels.window_preset_panel import WindowPresetIoPanel, WindowPresetParsePanel
from app.ui.panels.thumb_panel import ThumbCachePanel, ClipboardPanel
from app.ui.panels.url_panel import UrlPanel
from app.ui.panels.folder_panel import FolderScanPanel
from app.ui.panels.queue_panel import QueuePanel, QueueSelectionPanel
from app.ui.panels.folder_ai_panel import FolderAiPanel
from app.ui.panels.settings_panel import SettingsPanel, CdpConfigPanel
from app.ui.panels.presets_panel import ArenaPresetPanel, ArenaPresetRestorePanel, PromptPresetPanel
from app.ui.panels.run_panel import RunControlPanel, RunTabsPanel, TabInfoPanel, TabInfoPanel
from app.ui.panels.watcher_panel import WatcherPanel, WatcherConfigPanel
from app.ui.panels.pool_panel import PoolPanel, CooldownPanel
from app.ui.panels.captcha_panel import CaptchaPanel
from app.ui.panels.cdp_panel import CdpLoopPanel, TabsPanel, AutoConnectPanel, PopupPanel, ConnectPanel, FindTabPanel, CdpTestPanel
from app.ui.panels.highlight_panel import HighlightPanel

class Bridge(
    QObject,
    BridgeCore, ArenaStatePanel, JobStatusPanel, ActionBlocksPanel, ActionBlocksIoPanel, StackPresetsPanel, UndoEditPanel, UndoApplyPanel, UndoApiPanel, GridLayoutPanel, WindowPresetIoPanel, WindowPresetParsePanel, ThumbCachePanel, ClipboardPanel, UrlPanel, FolderScanPanel, QueuePanel, QueueSelectionPanel, FolderAiPanel, SettingsPanel, CdpConfigPanel, ArenaPresetPanel, ArenaPresetRestorePanel, PromptPresetPanel, RunControlPanel, RunTabsPanel, WatcherPanel, WatcherConfigPanel, PoolPanel, CooldownPanel, CaptchaPanel, CdpLoopPanel, TabsPanel, AutoConnectPanel, PopupPanel, ConnectPanel, FindTabPanel, CdpTestPanel, HighlightPanel,
):
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
        self._init_state_flags()
        self.undo_service = UndoService(self.config.undo)
        self.cdp = cdp_client
        self._init_thumbnail_infra()
        try:
            self.config.undo.load()
        except Exception:
            pass
        self._wire_cdp_client()
        self._watcher = self._build_watcher_service()
        self._watcher_loop_task = None
        self._page_pool = self._build_page_pool()
        self._log_build_version()

