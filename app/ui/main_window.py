"""MainWindow — QWebEngineView hosting the modern sash-grid UI with geometry persistence."""

from pathlib import Path

from PySide6.QtWidgets import QMainWindow
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge

try:
    from app.browser.cdp_client import CDPClient
except Exception:
    CDPClient = None


def _is_valid_geometry(saved: dict) -> bool:
    """Check geometry dict has int x/y and positive width/height — same as old app."""
    try:
        w = int(saved["width"])
        h = int(saved["height"])
        int(saved["x"])
        int(saved["y"])
        return w > 0 and h > 0
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


class MainWindow(QMainWindow):
    def __init__(self, state_path: Path = Path("config/app_state.json")):
        super().__init__()
        self.setWindowTitle("Arena Image Processor — Modern UI")
        self.resize(1600, 1000)

        # config manager for layout + presets + window geometry
        self.config_manager = ConfigManager(config_dir="config")

        # Restore window geometry if valid — position and size storable automatically
        self._restore_window_geometry()

        # state path for arena (legacy app_state)
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # CDP client for Chrome remote debugging — host/port from config so user can choose
        self.cdp_client = None
        if CDPClient:
            try:
                host = self.config_manager.get_state("cdp_host", "127.0.0.1")
                port = self.config_manager.get_state("cdp_port", 9222)
                self.cdp_client = CDPClient(host=host, port=port, parent=self)
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

    def _restore_window_geometry(self) -> None:
        """Restore saved window position and size if valid — called on startup."""
        try:
            saved = self.config_manager.get_state("window_geometry", None)
            if not isinstance(saved, dict):
                return
            if not _is_valid_geometry(saved):
                return
            x = int(saved["x"])
            y = int(saved["y"])
            w = int(saved["width"])
            h = int(saved["height"])
            # Clamp to reasonable screen area — avoid off-screen
            # Keep at least 100px visible
            self.setGeometry(x, y, w, h)
        except Exception:
            # Ignore any restore errors — keep default 1600x1000
            pass

    def _save_window_geometry(self) -> None:
        """Persist current window position and size — called automatically on closing."""
        try:
            g = self.geometry()
            self.config_manager.set_state(
                window_geometry={
                    "x": int(g.x()),
                    "y": int(g.y()),
                    "width": int(g.width()),
                    "height": int(g.height()),
                }
            )
        except Exception:
            # Never fail close due to geometry save
            pass

    def closeEvent(self, event):
        # Save window position and size automatically on closing — main win + sash-grid already flushed
        try:
            self._save_window_geometry()
        except Exception:
            pass
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
