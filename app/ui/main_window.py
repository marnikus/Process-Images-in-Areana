"""MainWindow — QWebEngineView hosting the modern sash-grid UI."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QMainWindow
from PySide6.QtCore import QUrl, QObject
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge


class MainWindow(QMainWindow):
    def __init__(self, state_path: Path = Path("config/app_state.json")):
        super().__init__()
        self.setWindowTitle("Arena Image Processor — Modern UI")
        self.resize(1600, 1000)

        # config manager for layout + presets
        self.config_manager = ConfigManager(config_dir="config")

        # state path for arena
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # Web view
        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)

        # Bridge
        self.bridge = Bridge(config_manager=self.config_manager, state_path=self.state_path, parent=self)

        # WebChannel
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        # Load UI
        index_path = Path(__file__).parent / "web" / "index.html"
        if not index_path.exists():
            # fallback to old location check
            raise FileNotFoundError(f"UI index.html not found at {index_path}")
        self.view.load(QUrl.fromLocalFile(str(index_path.resolve())))

        # optional: enable dev tools via right click? Keep simple

    def closeEvent(self, event):
        # Save arena state already handled by bridge, but ensure config saved
        try:
            self.config_manager.session.save()
            self.config_manager.window_presets.save()
        except Exception:
            pass
        super().closeEvent(event)
