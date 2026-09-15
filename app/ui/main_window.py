"""MainWindow — QWebEngineView hosting the modern sash-grid UI."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QMainWindow
from PySide6.QtCore import QUrl, QObject
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge

try:
    from app.browser.cdp_client import CDPClient
except Exception:
    CDPClient = None


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

        # CDP client for Chrome remote debugging
        self.cdp_client = None
        if CDPClient:
            try:
                self.cdp_client = CDPClient(host="127.0.0.1", port=9222, parent=self)
            except Exception as e:
                print(f"CDP client init failed: {e}")

        # Web view
        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)

        # Bridge
        self.bridge = Bridge(config_manager=self.config_manager, state_path=self.state_path, cdp_client=self.cdp_client, parent=self)

        # WebChannel
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        # Load UI
        index_path = Path(__file__).parent / "web" / "index.html"
        if not index_path.exists():
            raise FileNotFoundError(f"UI index.html not found at {index_path}")
        self.view.load(QUrl.fromLocalFile(str(index_path.resolve())))

    def closeEvent(self, event):
        try:
            self.config_manager.session.save()
            self.config_manager.window_presets.save()
            self.config_manager.undo.save()
            self.config_manager.presets.save()
            self.view.page().runJavaScript("typeof SashGrid !== 'undefined' && SashGrid.flushPersistence && SashGrid.flushPersistence()")
        except Exception:
            pass
        # disconnect CDP
        if self.cdp_client:
            try:
                import asyncio
                asyncio.ensure_future(self.cdp_client.disconnect())
            except Exception:
                pass
        super().closeEvent(event)
