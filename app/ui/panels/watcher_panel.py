"""Watcher Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
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




class WatcherPanel:

    def _on_watcher_state(self, payload: dict):
        """Callback from watcher service — emit to UI."""
        try:
            import json as _json
            self.watcher_status.emit(_json.dumps(payload, ensure_ascii=False))
            # Also log important transitions
            status = payload.get("status","")
            if status in ("waiting_captcha", "waiting_generation"):
                kind = payload.get("waiting_kind","")
                dur = payload.get("waiting_duration",0)
                if dur % 10 == 0 or dur < 5:  # log every 10s and first 5s
                    self._log(f"👁️ Watcher {status}: {kind} for {dur}s", "warn" if "captcha" in status else "info")
        except Exception as e:
            try:
                self._log(f"Watcher state emit failed: {e}", "warn")
            except Exception:
                pass

    @Slot(result=str)
    def start_watcher(self):
        try:
            if not self._watcher:
                from app.services.watcher import WatcherService, WatcherConfig
                cfg = WatcherConfig(
                    enabled=True,
                    check_interval_ms=int(self.config.get_state("watcher_interval_ms", 2000)),
                    captcha_timeout_sec=int(self.config.get_state("watcher_captcha_timeout_sec", 300)),
                    generation_timeout_sec=int(self.config.get_state("watcher_generation_timeout_sec", 600)),
                    auto_pause_jobs=bool(self.config.get_state("watcher_auto_pause", True)),
                )
                self._watcher = WatcherService(
                    config=cfg,
                    cdp_controller_getter=lambda: self._get_watcher_cdp_controller(),
                    job_runner_getter=lambda: self,
                    logger=lambda msg, level="info": self._log(f"[Watcher] {msg}", level)
                )
                self._watcher.add_callback(lambda p: self._on_watcher_state(p))
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
    def check_watcher_now(self):
        try:
            if not self._watcher:
                return json.dumps({"ok": False, "error": "watcher not initialized"})
            # Schedule immediate check
            self._schedule_coro(self._watcher.check_once())
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})


class WatcherConfigPanel:
    """Watcher config get/set + service lifecycle (W1.6 split)."""

    @Slot(result=str)
    def get_watcher_config(self):
        try:
            if self._watcher:
                # Ensure task is running if enabled and loop now available
                try:
                    self._watcher.ensure_task()
                except Exception:
                    pass
                cfg = self._watcher.get_config()
            else:
                cfg = {
                    "enabled": bool(self.config.get_state("watcher_enabled", False)),
                    "check_interval_ms": int(self.config.get_state("watcher_interval_ms", 2000)),
                    "captcha_timeout_sec": int(self.config.get_state("watcher_captcha_timeout_sec", 300)),
                    "generation_timeout_sec": int(self.config.get_state("watcher_generation_timeout_sec", 600)),
                    "auto_pause_jobs": bool(self.config.get_state("watcher_auto_pause", True)),
                }
            return json.dumps(cfg, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @Slot(str, result=str)
    def set_watcher_config(self, cfg_json: str):
        try:
            data = json.loads(cfg_json or "{}")
            vals = _watcher_cfg_values(data)
            self._watcher_persist(vals)
            self._watcher_update_or_create(vals)
            self._log(f"Watcher config saved: enabled={vals[0]} interval={vals[1]}ms captcha_to={vals[2]}s gen_to={vals[3]}s", "success")
            return _watcher_config_json(vals)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _watcher_persist(self, vals: tuple):
        """Persist validated watcher config to the session."""
        enabled, interval, captcha_to, gen_to, auto_pause = vals
        self.config.set_state(
            watcher_enabled=enabled,
            watcher_interval_ms=interval,
            watcher_captcha_timeout_sec=captcha_to,
            watcher_generation_timeout_sec=gen_to,
            watcher_auto_pause=auto_pause,
        )

    def _watcher_update_or_create(self, vals: tuple):
        """Push config to the live watcher (create+start when enabled)."""
        enabled, interval, captcha_to, gen_to, auto_pause = vals
        if self._watcher:
            self._watcher.update_config(
                enabled=enabled,
                check_interval_ms=interval,
                captcha_timeout_sec=captcha_to,
                generation_timeout_sec=gen_to,
                auto_pause_jobs=auto_pause,
            )
        elif enabled:
            self._watcher_create(vals)

    def _watcher_create(self, vals: tuple):
        """Create + start the watcher service when none exists yet."""
        from app.services.watcher import WatcherService, WatcherConfig
        enabled, interval, captcha_to, gen_to, auto_pause = vals
        cfg_obj = WatcherConfig(
            enabled=enabled,
            check_interval_ms=interval,
            captcha_timeout_sec=captcha_to,
            generation_timeout_sec=gen_to,
            auto_pause_jobs=auto_pause,
        )
        self._watcher = WatcherService(
            config=cfg_obj,
            cdp_controller_getter=lambda: self._get_watcher_cdp_controller(),
            job_runner_getter=lambda: self,
            logger=lambda msg, level="info": self._log(f"[Watcher] {msg}", level)
        )
        self._watcher.add_callback(lambda p: self._on_watcher_state(p))
        self._watcher.start()



def _watcher_cfg_values(data: dict) -> tuple:
    """(enabled, interval_ms, captcha_to, gen_to, auto_pause) — clamped."""
    enabled = bool(data.get("enabled", False))
    interval = max(500, min(int(data.get("check_interval_ms", 2000)), 30000))  # 0.5s to 30s
    captcha_to = max(10, min(int(data.get("captcha_timeout_sec", 300)), 3600))
    gen_to = max(30, min(int(data.get("generation_timeout_sec", 600)), 3600))
    auto_pause = bool(data.get("auto_pause_jobs", True))
    return enabled, interval, captcha_to, gen_to, auto_pause


def _watcher_config_json(vals: tuple) -> str:
    """ok-json echoing the validated watcher config."""
    enabled, interval, captcha_to, gen_to, auto_pause = vals
    return json.dumps({"ok": True, "config": {
        "enabled": enabled,
        "check_interval_ms": interval,
        "captcha_timeout_sec": captcha_to,
        "generation_timeout_sec": gen_to,
        "auto_pause_jobs": auto_pause,
    }}, ensure_ascii=False)
