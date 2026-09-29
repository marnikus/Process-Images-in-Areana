from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import QUrl
from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge
from app.ui.panels.browser_tabs import start_url_reconciler
from app.ui.services.captcha_recordings_bridge import CaptchaRecordingsBridge
from .console import _build_view

try:
    from app.browser.cdp_client import CDPClient
except Exception:
    CDPClient = None

def _build_services(window, state_path: Path):
    window.config_manager = ConfigManager(config_dir="config")
    window.state_path = Path(state_path)
    window.state_path.parent.mkdir(parents=True, exist_ok=True)
    _init_cdp_client(window)

def _init_cdp_client(window) -> None:
    window.cdp_client = None
    if CDPClient:
        try:
            host = window.config_manager.get_state("cdp_host", "127.0.0.1")
            port = window.config_manager.get_state("cdp_port", 9222)
            window.cdp_client = CDPClient(host=host, port=port, parent=window)
        except Exception as e:
            print(f"CDP client init failed: {e}")

def _build_ui(window):
    window.view = _build_view(window)
    window.setCentralWidget(window.view)
    _configure_web_settings(window)
    window.bridge = Bridge(config_manager=window.config_manager, state_path=window.state_path, cdp_client=window.cdp_client, parent=window)
    window.recordings_bridge = CaptchaRecordingsBridge(window.bridge._captcha_service().recordings, window)
    start_url_reconciler(window.bridge)
    _attach_web_channel(window)

def _configure_web_settings(window) -> None:
    try:
        from PySide6.QtWebEngineCore import QWebEngineSettings
        settings = window.view.page().settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
    except Exception as e:
        print(f"WebEngine settings tweak failed: {e}")

def _attach_web_channel(window) -> None:
    from PySide6.QtWebChannel import QWebChannel
    window.channel = QWebChannel(window.view.page())
    window.channel.registerObject("bridge", window.bridge)
    window.channel.registerObject("captchaRecordings", window.recordings_bridge)
    window.view.page().setWebChannel(window.channel)

def _load_index(window) -> None:
    index_path = Path(__file__).parent.parent / "web" / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(f"UI index.html not found at {index_path}")
    window.view.load(QUrl.fromLocalFile(str(index_path.resolve())))
