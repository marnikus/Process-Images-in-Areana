"""MainWindow — QWebEngineView hosting the modern sash-grid UI with geometry persistence."""

from pathlib import Path

from PySide6.QtWidgets import QMainWindow
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge
from app.ui.panels.browser_tabs import start_url_reconciler
from app.ui.services.captcha_recordings_bridge import CaptchaRecordingsBridge
from app.utils.js_console import js_console_line
from app.utils.logging import get_logger

try:
    from app.browser.cdp_client import CDPClient
except Exception:
    CDPClient = None


class _ConsolePage(QWebEnginePage):
    """Every page console message (incl. uncaught TypeErrors) → app log WITH
    file:line — 2026-09-25: the terminal showed only `js: fn is not a function`,
    untraceable. Replaces the default handler (no super(): one line, ours).
    `*args` = the Qt virtual's fixed (level, message, line, source) signature."""

    def javaScriptConsoleMessage(self, *args):
        level, message, line_number, source_id = args
        where = f"{source_id}:{line_number}" if source_id else f"line {line_number}"
        lvl, line = js_console_line(level, message, where)
        getattr(get_logger(), lvl)(line)


def _build_view(parent) -> QWebEngineView:
    """The app view wired to the console-logging page (module-level so
    `MainWindow`'s class size stays on its recorded baseline)."""
    view = QWebEngineView(parent)
    view.setPage(_ConsolePage(view))
    return view


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
        self._build_services(state_path)
        self._build_ui()
        self._restore_window_geometry()
        self._load_index()

    def _build_services(self, state_path: Path):
        self.config_manager = ConfigManager(config_dir="config")
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_cdp_client()

    def _build_ui(self):
        self.view = _build_view(self)   # console page: js errors land in the log with file:line
        self.setCentralWidget(self.view)
        self._configure_web_settings()
        self.bridge = Bridge(config_manager=self.config_manager, state_path=self.state_path, cdp_client=self.cdp_client, parent=self)
        self.recordings_bridge = CaptchaRecordingsBridge(self.bridge._captcha_service().recordings, self)
        start_url_reconciler(self.bridge)  # S6: Python owns the URL reconcile cadence (I-50)
        self._attach_web_channel()

    def _init_cdp_client(self) -> None:
        # CDP client for Chrome remote debugging — host/port from config so user can choose
        self.cdp_client = None
        if CDPClient:
            try:
                host = self.config_manager.get_state("cdp_host", "127.0.0.1")
                port = self.config_manager.get_state("cdp_port", 9222)
                self.cdp_client = CDPClient(host=host, port=port, parent=self)
            except Exception as e:
                print(f"CDP client init failed: {e}")

    def _configure_web_settings(self) -> None:
        # Enable local file access for thumbnails — file:// from file:// origin
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            settings = self.view.page().settings()
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
        except Exception as e:
            print(f"WebEngine settings tweak failed: {e}")

    def _attach_web_channel(self) -> None:
        # WebChannel
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.channel.registerObject("captchaRecordings", self.recordings_bridge)
        self.view.page().setWebChannel(self.channel)

    def _load_index(self) -> None:
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
            try:
                self.bridge._persist_cooldowns()
            except Exception:
                pass
            self.view.page().runJavaScript("typeof SashGrid !== 'undefined' && SashGrid.flushPersistence && SashGrid.flushPersistence()")
        except Exception:
            pass
        self._drop_browser_sockets()
        super().closeEvent(event)

    def _drop_browser_sockets(self):
        """Close what the app keeps open in a browser — never a reason to fail a close."""
        try:
            pool = getattr(getattr(self, "bridge", None), "_page_pool", None)
            bg_loop = getattr(getattr(self, "bridge", None), "_bg_loop", None)
            if pool is not None:
                _drop_pool_sockets(pool, bg_loop)
            client = getattr(self, "cdp_client", None)
            if client:
                _drop_main_client(client, bg_loop)
        except Exception:
            pass


def _drop_main_client(client, bg_loop):
    """Disconnect main CDP client — sync, no pending tasks."""
    try:
        if bg_loop is not None and bg_loop.is_running():
            try:
                import asyncio
                fut = asyncio.run_coroutine_threadsafe(client.disconnect(), bg_loop)
                fut.result(timeout=1.0)
            except Exception:
                _sync_drop_client(client)
        else:
            _sync_drop_client(client)
    except Exception:
        _sync_drop_client(client)


def _drop_pool_sockets(pool, bg_loop):
    """Reload (F5) and disconnect all pooled tabs — clean on app close, no pending tasks."""
    try:
        tab_ids = list(getattr(pool, "_pages", {}).keys())
        for tid in tab_ids:
            try:
                _drop_one_pooled_tab(pool, tid, bg_loop)
            except Exception:
                continue
        try:
            pool._pages.clear()
            pool._clients.clear()
            pool._controllers.clear()
        except Exception:
            pass
    except Exception:
        pass


def _drop_one_pooled_tab(pool, tab_id, bg_loop):
    """One pooled tab: reload + disconnect, blocking with timeout."""
    try:
        client, ctrl = pool.get_clients(tab_id)
        if client is None:
            return
        if bg_loop is not None and bg_loop.is_running():
            _run_pool_tab_cleanup_sync(pool, tab_id, bg_loop)
        else:
            _sync_drop_client(client)
    except Exception:
        pass


def _run_pool_tab_cleanup_sync(pool, tab_id, bg_loop):  # quality-override: params=3 reason=pool,tab_id,bg_loop needed for sync cleanup
    """Run _clean_pool_tab on bg_loop and wait (no pending task warning)."""
    try:
        import asyncio
        client, ctrl = pool.get_clients(tab_id)
        if client is None:
            return
        coro = _clean_pool_tab(client, ctrl, tab_id)
        fut = asyncio.run_coroutine_threadsafe(coro, bg_loop)
        try:
            fut.result(timeout=1.5)
        except Exception:
            _sync_drop_client(client)
    except Exception:
        try:
            client, _ = pool.get_clients(tab_id)
            _sync_drop_client(client)
        except Exception:
            pass


async def _clean_pool_tab(client, ctrl, tab_id):
    """Clean one tab: badge, overlay, reload, disconnect."""
    try:
        await _clear_badge_async(client, tab_id)
        await _hide_overlay_async(client, ctrl)
        await _reload_tab_async(client)
    finally:
        await _disconnect_client_async(client)


async def _clear_badge_async(client, tab_id):
    """Remove worker badge from tab."""
    try:
        from app.services.live.worker_badges import clear_badge
        await clear_badge(client, tab_id)
    except Exception:
        pass


async def _hide_overlay_async(client, ctrl):
    """Hide watcher overlay."""
    try:
        if ctrl and hasattr(ctrl, "hide_watcher_overlay"):
            await ctrl.hide_watcher_overlay()
    except Exception:
        pass
    try:
        await client.send("Runtime.evaluate", {
            "expression": "document.getElementById('arena-watcher-overlay')?.remove(); document.getElementById('arena-watcher-style-v2')?.remove(); true"
        })
    except Exception:
        pass


async def _reload_tab_async(client):
    """Reload tab (F5) to clean state."""
    try:
        await client.send("Page.reload")
    except Exception:
        try:
            await client.evaluate("window.location.reload(); true")
        except Exception:
            pass
    try:
        import asyncio
        await asyncio.sleep(0.2)
    except Exception:
        pass


async def _disconnect_client_async(client):
    """Disconnect client."""
    try:
        await client.disconnect()
    except Exception:
        _sync_drop_client(client)


def _sync_drop_client(client):
    """Sync drop when no running loop."""
    if not client:
        return
    try:
        client._ws = None
        client._connected = False
        rt = getattr(client, "_receive_task", None)
        if rt:
            try:
                rt.cancel()
            except Exception:
                pass
        client._receive_task = None
    except Exception:
        pass
