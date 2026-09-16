"""Auto-connect slots for the Bridge (spec 01-04: no manual URL connection).

Mixed into :class:`app.ui.bridge.Bridge`. This file is only wiring — detection
lives in ``app/browser/autoconnect_match``, linking in ``PageLinker``, scheduling
in ``ScanScheduler``, and the Chrome/pool adapters in ``PageConnector``.

Settings (storable in ``config/session.json`` and in arena preset JSON):
``autoconnect_enabled``, ``autoconnect_url_pattern``, ``autoconnect_interval_ms``,
``autoconnect_max_pages``, ``autoconnect_primary`` plus ``cdp_host`` / ``cdp_port``.
"""

from __future__ import annotations

import json

try:
    from PySide6.QtCore import Slot
except ImportError:  # headless tests / no Qt
    def Slot(*_a, **_kw):
        def deco(fn):
            return fn
        return deco

from app.browser.autoconnect_config import config_from_getter
from app.browser.autoconnect_linker import PageLinker
from app.browser.autoconnect_service import AutoConnectService, ScanScheduler, ServiceHooks
from app.ui.autoconnect_pages import PageConnector
from app.ui.autoconnect_settings import describe, preset_doc, storable_from_payload, storable_from_preset


class AutoConnectMixin:
    """Slots + boot wiring for automatic page discovery and linking."""

    # provided by Bridge: config, cdp, _page_pool, _log, _schedule_coro,
    # _emit_pool_status, _do_connect_page_pool, _do_connect_tab, autoconnect_status

    def _init_autoconnect(self) -> None:
        """Build the service; called at the end of ``Bridge.__init__``."""
        self._autoconnect = None
        self._autoconnect_loop = None
        try:
            hooks = ServiceHooks(on_status=self._emit_autoconnect_status,
                                 logger=lambda m, lvl="info": self._log(m, lvl))
            connector = PageConnector(self, self._autoconnect_config)
            linker = PageLinker(pool=self._page_pool, connect_page=connector.link,
                                disconnect_page=connector.unlink, logger=hooks.log)
            service = AutoConnectService(fetch_tabs=connector.fetch, linker=linker,
                                         config=config_from_getter(self.config.get_state), hooks=hooks)
            self._autoconnect = service
            self._autoconnect_loop = ScanScheduler(service)
        except Exception as e:
            self._log(f"Auto-connect init failed: {e}", "warn")

    def _start_autoconnect_boot(self) -> None:
        """Auto-link matching pages on app start — no manual Add step (spec 03)."""
        service, loop = self._autoconnect, self._autoconnect_loop
        if not service or not loop:
            return
        try:
            cfg = service.reload_config(self.config.get_state)
            if not cfg.enabled:
                self._log("🤖 Auto-connect is OFF — enable it in Settings to link pages automatically", "info")
                return
            self._log(f"🤖 Auto-connect on start: scanning {cfg.endpoint} for “{cfg.url_pattern}” pages", "info")
            self._schedule_coro(loop.run())
        except Exception as e:
            self._log(f"Auto-connect boot failed: {e}", "warn")

    def shutdown_autoconnect(self) -> None:
        """App closing: stop the scan loop and the new-tab event stream."""
        loop = getattr(self, "_autoconnect_loop", None)
        if not loop:
            return
        try:
            loop.halt()
        except Exception as e:
            self._log(f"Auto-connect shutdown failed: {e}", "warn")

    # ---- config plumbing ----
    def _autoconnect_config(self):
        service = getattr(self, "_autoconnect", None)
        return service.config if service else config_from_getter(self.config.get_state)

    def _autoconnect_payload(self, report: dict | None = None) -> dict:
        service = getattr(self, "_autoconnect", None)
        loop = getattr(self, "_autoconnect_loop", None)
        payload = self._autoconnect_config().to_dict()
        payload["running"] = bool(loop and loop.running)
        payload.update(report or (service.last_report if service else {}))
        return payload

    def _emit_autoconnect_status(self, report: dict) -> None:
        try:
            self.autoconnect_status.emit(json.dumps(self._autoconnect_payload(report), ensure_ascii=False))
        except Exception:
            pass

    def _apply_autoconnect_config(self) -> None:
        """Push stored settings into the running loop (start/stop/rescan)."""
        service, loop = self._autoconnect, self._autoconnect_loop
        if not service or not loop:
            return
        was_running = loop.running
        cfg = service.reload_config(self.config.get_state)
        if not cfg.enabled:
            if was_running:
                self._schedule_coro(loop.stop())
            return
        if was_running:
            loop.request_scan("settings")
        else:
            self._schedule_coro(loop.run())

    # ---- slots ----
    @Slot(result=str)
    def get_autoconnect_config(self):
        try:
            return json.dumps(self._autoconnect_payload(), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def set_autoconnect_config(self, cfg_json: str):
        try:
            storable = storable_from_payload(json.loads(cfg_json or "{}"))
            self.config.set_state(**storable)
            self._apply_autoconnect_config()
            cfg = self._autoconnect_config()
            self._log(describe(cfg), "success")
            return json.dumps({"ok": True, "config": self._autoconnect_payload()}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @Slot(result=str)
    def autoconnect_scan_now(self):
        """Manual re-scan — same pass the timer runs (spec 03)."""
        try:
            service = self._autoconnect
            if not service:
                return json.dumps({"ok": False, "error": "auto-connect unavailable"})
            service.reload_config(self.config.get_state)
            self._schedule_coro(service.scan_once(reason="manual"))
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @Slot(result=str)
    def get_autoconnect_status(self):
        return self.get_autoconnect_config()

    # ---- arena preset round-trip (all UI params storable) ----
    def _autoconnect_preset_doc(self) -> dict:
        return preset_doc(self._autoconnect_config())

    def _restore_autoconnect_preset(self, doc: dict) -> None:
        try:
            self.config.set_state(**storable_from_preset(doc))
            self._apply_autoconnect_config()
            self._log("Restored auto-connect settings from preset", "info")
        except Exception as e:
            self._log(f"Auto-connect preset restore failed: {e}", "warn")
