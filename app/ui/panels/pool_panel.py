"""Pool Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
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




class PoolPanel:

    def _emit_pool_status(self):
        try:
            if not self._page_pool:
                return
            snap = self._page_pool.status_snapshot()
            self.page_pool_updated.emit(json.dumps(snap, ensure_ascii=False))
            self._persist_cooldowns()
        except Exception:
            pass

    @Slot(result=str)
    def get_page_pool_status(self):
        try:
            if not self._page_pool:
                return json.dumps({"total": 0, "steady": 0, "busy": 0, "cooling": 0, "free": 0, "pages": []})
            try:
                from app.services.cooldown_service import refresh_expired
                for _tid in refresh_expired(self._page_pool):
                    self._log(f"✅ Page {_tid[:12]} cooldown expired — STEADY ready", "success")
            except Exception:
                pass
            snap = self._page_pool.status_snapshot()
            self.page_pool_updated.emit(json.dumps(snap, ensure_ascii=False))
            self._persist_cooldowns()
            return json.dumps(snap, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @Slot(result=str)
    def clear_page_pool(self):
        try:
            if not self._page_pool:
                return json.dumps({"ok": True, "cleared": 0})
            snap = self._page_pool.status_snapshot()
            count = snap.get("total", 0)
            # Clear internal dicts
            try:
                self._page_pool._pages.clear()
                self._page_pool._clients.clear()
                self._page_pool._controllers.clear()
            except Exception:
                pass
            try:
                from app.persistence.cooldown_store import save_entries
                save_entries(self._cooldowns_path(), {})
            except Exception:
                pass
            self._emit_pool_status()
            self._log(f"Page pool cleared {count} pages", "warn")
            return json.dumps({"ok": True, "cleared": count})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def connect_page_pool(self, ws_url: str):
        try:
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            if not ws_url:
                return json.dumps({"ok": False, "error": "empty ws_url"})
            self._log(f"🔗 Adding tab to pool {ws_url[:80]}… steady", "info")
            self._schedule_coro(self._do_connect_page_pool(ws_url))
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def disconnect_page_pool(self, tab_id: str):
        try:
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            ok = self._page_pool.remove_page(tab_id)
            self._emit_pool_status()
            if ok:
                self._log(f"Pool page {tab_id[:12]} removed", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def clear_watcher_overlay(self):
        try:
            if self._watcher:
                import asyncio
                # Schedule clear
                cdp = self._get_watcher_cdp_controller()
                if cdp:
                    self._schedule_coro(cdp.hide_watcher_overlay())
                self._schedule_coro(self._watcher.force_clear())
            else:
                cdp = self._get_watcher_cdp_controller()
                if cdp:
                    self._schedule_coro(cdp.hide_watcher_overlay())
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _pooled_ids(self) -> set:
        """Ids currently in the pool; empty when pool is unavailable."""
        try:
            return set(self._page_pool._pages.keys())
        except Exception:
            return set()

    async def _do_connect_page_pool(self, ws_url: str):
        try:
            from app.browser.cdp_client import CDPClient
            from app.browser.cdp_arena import CDPArenaController
            from app.browser.page_status import PageInfo
            import re
            m = re.search(r'/devtools/page/([^/]+)$', ws_url)
            tab_id = m.group(1) if m else ws_url
            host = self._page_pool._host if self._page_pool else "127.0.0.1"
            port = self._page_pool._port if self._page_pool else 9222
            client = CDPClient(host=host, port=port)
            ok = await client.connect(ws_url)
            if not ok:
                self._log(f"❌ Pool connect failed {ws_url[:80]}", "error")
                return
            ctrl = CDPArenaController(client, log_callback=lambda msg: self._log(msg, "info"))
            live_title, live_url = await self._resolve_tab_info(tab_id, ws_url)
            info = PageInfo(tab_id=tab_id, ws_url=ws_url, title=live_title or tab_id, url=live_url or "")
            self._page_pool.add_page(info)
            self._page_pool.register_client(tab_id, client, ctrl)
            self._restore_page_state(tab_id)
            self._emit_pool_status()
            total, free = self._page_pool.get_counts()
            self._log(f"✅ Pool added {tab_id[:12]} steady — {info.title[:40]} — total {total} free {free}", "success")
            if total >= 2:
                self._log(f"✅ {total} tabs in pool ready for parallel — 2+ images will dispatch to different webpages", "success")
        except Exception as e:
            self._log(f"Pool connect exception {e}", "error")


class CooldownPanel:

    def _cooldowns_path(self):
        """config/cooldowns.json next to the other stores."""
        try:
            base = getattr(self.config, "dir", None)
            if base:
                return str(Path(base) / "cooldowns.json")
        except Exception:
            pass
        return "config/cooldowns.json"

    def _persist_cooldowns(self):
        """Autosave wall-clock timers + job counters across restarts."""
        try:
            if not self._page_pool:
                return
            from app.persistence.cooldown_store import save_pool_snapshot
            save_pool_snapshot(self._cooldowns_path(), self._page_pool)
            if not self._persist_ok:
                self._persist_ok = True
                self._log("✅ Cooldown autosave recovered", "success")
        except Exception as e:
            if self._persist_ok:
                self._persist_ok = False
                self._log(f"⚠ Cooldown autosave failing ({e}) — timers will NOT survive restart", "warn")

    @Slot(result=str)
    def get_cooldown_config(self):
        try:
            from app.core.cooldown import config_to_dict
            from app.services.cooldown_service import load_config
            cfg = load_config(self.config.get_state)
            return json.dumps({"ok": True, "config": config_to_dict(cfg)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def set_cooldown_config(self, cfg_json: str):
        try:
            from app.core.cooldown import clamp_seconds
            data = json.loads(cfg_json or "{}")
            enabled = bool(data.get("enabled", True))
            min_s = clamp_seconds(data.get("min_seconds", 300), 300)
            pen_s = clamp_seconds(data.get("captcha_penalty_seconds", 900), 900)
            rl_s = clamp_seconds(data.get("rate_limit_penalty_seconds", 1800), 1800)
            self.config.set_state(cooldown_enabled=enabled, cooldown_min_seconds=min_s,
                                  cooldown_captcha_penalty_seconds=pen_s,
                                  cooldown_rate_limit_penalty_seconds=rl_s)
            self._log(f"Cooldown set: enabled={enabled} min={min_s // 60}m penalty={pen_s // 60}m per captcha limit={rl_s // 60}m", "success")
            return json.dumps({"ok": True, "config": {"enabled": enabled, "min_seconds": min_s,
                                                      "captcha_penalty_seconds": pen_s,
                                                      "rate_limit_penalty_seconds": rl_s}}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def reset_page_cooldown(self, tab_id: str):
        try:
            from app.services.cooldown_service import is_stuck_status, reset_cooldown
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            page = self._page_pool.get_page(tab_id)
            if page is None:
                return json.dumps({"ok": False, "error": "unknown tab"})
            if is_stuck_status(page.status):
                return self._reset_stuck_page(tab_id, page)
            if reset_cooldown(self._page_pool, tab_id):
                self._emit_pool_status()
                self._log(f"♻️ Cooldown reset for {(tab_id or '')[:12]} — tab ready", "success")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "unknown tab"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, int, result=str)
    def set_page_cooldown(self, tab_id: str, seconds: int):
        try:
            from app.core.cooldown import format_remaining
            from app.services.cooldown_service import edit_cooldown
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            if edit_cooldown(self._page_pool, tab_id, int(seconds or 0)):
                self._emit_pool_status()
                left = format_remaining(int(seconds or 0))
                self._log(f"⏳ Cooldown for {(tab_id or '')[:12]} set to {left}", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "unknown tab or job running"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _reset_stuck_page(self, tab_id: str, page) -> str:
        """Force-free a stuck page; refuses while its own job is alive."""
        from app.services.cooldown_service import force_reset_page, tab_has_live_job
        was = getattr(page.status, "value", page.status)
        if tab_has_live_job(self._page_pool, tab_id):
            self._log(f"⚠ Reset refused for {(tab_id or '')[:12]} — job still running on this tab; stop it first", "warn")
            return json.dumps({"ok": False, "error": "job still running on this tab — stop it first"})
        if force_reset_page(self._page_pool, tab_id):
            self._emit_pool_status()
            self._log(f"♻️ Stuck {was} reset for {(tab_id or '')[:12]} (no run active) — tab ready, fix and run again", "success")
            return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "unknown tab"})
