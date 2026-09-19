"""Watcher + CAPTCHA panel — passive watcher config/control, 2Captcha settings.

Owns the 10 watcher/captcha slots (R5): thin slots delegate to module
funcs. Watcher construction is shared (`create_watcher_service`); the
watcher/captcha/CDP imports stay lazy (load-bearing fault tolerance:
import failure must degrade to err JSON / None, never break panel
import). `Bridge._captcha_service` stays a 2-line delegation: main_window
and app/services/captcha call that seam. Imports go panels -> services
only (Qt via qt_compat; asyncio for fire-and-forget tasks).
"""

import asyncio
import json

from app.ui.qt_compat import Slot
from app.services.run_state import schedule_coro


def _watcher_captcha_service(bridge):
    """Build the Watcher-owned provider facade for a new Watcher instance."""
    from app.services.watcher_captcha import WatcherCaptchaService
    return WatcherCaptchaService(str(bridge.config.dir), bridge._log)



def _pool_watcher_controllers(pool):
    pages = pool.status_snapshot().get("pages", [])
    pairs = []
    for page in pages:
        tab_id = page.get("tab_id", "")
        _, controller = pool.get_clients(tab_id)
        if controller:
            pairs.append((tab_id, controller))
    return pairs


def get_watcher_cdp_controllers(bridge):
    """Return every connected pool page as ``(tab_id, controller)`` pairs."""
    pool = getattr(bridge, "_page_pool", None)
    try:
        pairs = _pool_watcher_controllers(pool) if pool else []
    except Exception:
        pairs = []
    if pairs:
        return pairs
    controller = get_watcher_cdp_controller(bridge)
    return [("primary", controller)] if controller else []


def get_watcher_cdp_controller(bridge):
    """Compatibility accessor for the first connected page."""
    try:
        if not bridge.cdp or not getattr(bridge.cdp, "is_connected", False):
            return None
        from app.browser.cdp_arena import CDPArenaController
        return CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
    except Exception:
        return None


def on_watcher_state(bridge, payload: dict):
    """Watcher-service callback — emit to UI, log key transitions."""
    try:
        bridge.watcher_status.emit(json.dumps(payload, ensure_ascii=False))
        status = payload.get("status", "")
        if status in ("waiting_captcha", "waiting_generation"):
            kind = payload.get("waiting_kind", "")
            dur = payload.get("waiting_duration", 0)
            if dur % 10 == 0 or dur < 5:  # log every 10s and first 5s
                bridge._log(f"👁️ Watcher {status}: {kind} for {dur}s",
                            "warn" if "captcha" in status else "info")
    except Exception as e:
        try:
            bridge._log(f"Watcher state emit failed: {e}", "warn")
        except Exception:
            pass


def watcher_config_values(config, enabled=None) -> dict:
    """Watcher fields from config state (enabled overridable)."""
    values = {
        "enabled": bool(config.get_state("watcher_enabled", False)),
        "check_interval_ms": int(config.get_state("watcher_interval_ms", 2000)),
        "captcha_timeout_sec": int(config.get_state("watcher_captcha_timeout_sec", 300)),
        "generation_timeout_sec": int(config.get_state("watcher_generation_timeout_sec", 600)),
        "auto_pause_jobs": bool(config.get_state("watcher_auto_pause", True)),
    }
    if enabled is not None:
        values["enabled"] = enabled
    return values


def parse_watcher_config(data: dict) -> dict:
    """Validate + clamp a watcher config payload (canonical names)."""
    return {
        "enabled": bool(data.get("enabled", False)),
        "check_interval_ms": max(500, min(int(data.get("check_interval_ms", 2000)), 30000)),
        "captcha_timeout_sec": max(10, min(int(data.get("captcha_timeout_sec", 300)), 3600)),
        "generation_timeout_sec": max(30, min(int(data.get("generation_timeout_sec", 600)), 3600)),
        "auto_pause_jobs": bool(data.get("auto_pause_jobs", True)),
    }


def create_watcher_service(bridge, values: dict):
    """Build + wire a WatcherService (caller decides when to start)."""
    from app.services.watcher import WatcherService, WatcherConfig
    captcha = _watcher_captcha_service(bridge)
    config = values if isinstance(values, WatcherConfig) else WatcherConfig(**values)
    watcher = WatcherService(
        config=config,
        cdp_controller_getter=lambda: get_watcher_cdp_controllers(bridge),
        job_runner_getter=lambda: bridge,
        logger=lambda msg, level="info": bridge._log(f"[Watcher] {msg}", level),
    )
    watcher._handlers._captcha_solver = captcha.solver
    watcher.add_callback(lambda p: on_watcher_state(bridge, p))
    return watcher


def persist_watcher_config(config, values: dict) -> None:
    """Persist validated watcher fields to session state."""
    config.set_state(
        watcher_enabled=values["enabled"],
        watcher_interval_ms=values["check_interval_ms"],
        watcher_captcha_timeout_sec=values["captcha_timeout_sec"],
        watcher_generation_timeout_sec=values["generation_timeout_sec"],
        watcher_auto_pause=values["auto_pause_jobs"],
    )


def captcha_service(bridge):
    """Lazy Watcher-only provider service; no image pipeline dependency."""
    svc = getattr(bridge, "_captcha_service_obj", None)
    if svc is None:
        from app.services.watcher_captcha import WatcherCaptchaService
        svc = bridge._captcha_service_obj = WatcherCaptchaService(
            str(bridge.config.dir), bridge._log)
    return svc


class WatcherCaptchaMixin:
    """Passive-watcher config/control and 2Captcha settings slots.

    ideal-size: 10 frozen JS slots; validate/wire helpers already live at
    module level — remaining per-slot bodies cannot move without
    scattering slot+helper pairs (R10.10).
    """

    @Slot(result=str)
    def get_watcher_config(self):
        try:
            if self._watcher:
                try:
                    self._watcher.ensure_task()
                except Exception:
                    pass
                cfg = self._watcher.get_config()
            else:
                cfg = watcher_config_values(self.config)
            return json.dumps(cfg, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @Slot(str, result=str)
    def set_watcher_config(self, cfg_json: str):
        try:
            values = parse_watcher_config(json.loads(cfg_json or "{}"))
            persist_watcher_config(self.config, values)
            if self._watcher:
                self._watcher.update_config(**values)
            elif values["enabled"]:
                self._watcher = create_watcher_service(self, values)
                self._watcher.start()
            self._log(f"Watcher config saved: enabled={values['enabled']}"
                      f" interval={values['check_interval_ms']}ms"
                      f" captcha_to={values['captcha_timeout_sec']}s"
                      f" gen_to={values['generation_timeout_sec']}s", "success")
            return json.dumps({"ok": True, "config": values}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def start_watcher(self):
        try:
            if not self._watcher:
                self._watcher = create_watcher_service(
                    self, watcher_config_values(self.config, enabled=True))
            self._watcher.update_config(enabled=True)
            self.config.set_state(watcher_enabled=True)
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def stop_watcher(self):
        try:
            if self._watcher:
                self._watcher.update_config(enabled=False)
            self.config.set_state(watcher_enabled=False)
            self._log("Watcher stopped by user", "warn")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_watcher_state(self):
        try:
            if not self._watcher:
                return json.dumps({"status": "idle", "enabled": False}, ensure_ascii=False)
            state = self._watcher.get_state()
            cfg = self._watcher.get_config()
            return json.dumps({**state, "config": cfg}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @Slot(result=str)
    def clear_watcher_overlay(self):
        try:
            cdp = get_watcher_cdp_controller(self)
            if cdp:
                schedule_coro(self, cdp.hide_watcher_overlay())
            if self._watcher:
                schedule_coro(self, self._watcher.force_clear())
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def check_watcher_now(self):
        try:
            if not self._watcher:
                return json.dumps({"ok": False, "error": "watcher not initialized"})
            schedule_coro(self, self._watcher.check_once())
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def set_captcha_settings(self, payload_json: str):
        """Save 2Captcha key/enable/timeout; key stays local (masked in reply)."""
        try:
            data = json.loads(payload_json or "{}")
            key = str(data.get("api_key", "") or "").strip()
            enabled = bool(data.get("enabled", False))
            timeout = int(data.get("solve_timeout_sec", 180))
            result = captcha_service(self).apply_settings(key, enabled, timeout)
            self._log(f"🔐 2Captcha settings saved (key={'set' if key else 'empty'},"
                      f" enabled={result['enabled']}, timeout={timeout}s)", "success")
            if result["enabled"]:
                asyncio.create_task(captcha_service(self).refresh_balance())
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        return json.dumps(result, ensure_ascii=False)

    @Slot(result=str)
    def get_captcha_status(self):
        """Key mask + balance + last error; raw key never leaves the store."""
        try:
            svc = captcha_service(self)
            if svc.status_payload().get("has_key"):
                asyncio.create_task(svc.refresh_balance())  # fire-and-forget, next call shows it
            return json.dumps({"ok": True, **svc.status_payload()}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_captcha_stats(self):
        """Local solve counters + auto success rate + balance (API stat)."""
        try:
            return json.dumps({"ok": True, **captcha_service(self).stats_payload()}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
