from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import QMainWindow
from .console import _is_valid_geometry
from .geometry import _restore_window_geometry, _save_window_geometry
from .services import _build_services, _build_ui, _load_index
from .cleanup import _drop_browser_sockets

class MainWindow(QMainWindow):
    def __init__(self, state_path: Path = Path("config/app_state.json")):
        super().__init__()
        self.setWindowTitle("Arena Image Processor — Modern UI")
        self.resize(1600, 1000)
        _build_services(self, state_path)
        _build_ui(self)
        _restore_window_geometry(self, self.config_manager, _is_valid_geometry)
        _load_index(self)

    def _save_window_geometry(self) -> None:
        _save_window_geometry(self, self.config_manager)

    def _restore_window_geometry(self) -> None:
        _restore_window_geometry(self, self.config_manager, _is_valid_geometry)

    def closeEvent(self, event):
        try:
            self._save_window_geometry()
        except Exception:
            pass
        try:
            self.config_manager.session.save()
            self.config_manager.window_presets.save()
            self.config_manager.undo.save()
            self.config_manager.presets.save()
            try:
                self.bridge._persist_cooldowns()
            except Exception:
                pass
            self.view.page().runJavaScript("typeof SashGrid !== 'undefined' && SashGrid.flushPersistence && SashGrid.flushPersistence()")
        except Exception:
            pass
        _drop_browser_sockets(self)
        super().closeEvent(event)
