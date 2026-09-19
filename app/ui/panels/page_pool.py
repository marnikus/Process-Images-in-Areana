"""Page pool panel — pooled tabs, cooldown config, per-tab cooldown control.

Owns the 9 pool slots (R6): thin slots delegate to module funcs. Cooldown
persistence/restore runs through app/services/run_state (contract §2):
`Bridge._persist_cooldowns` delegates there, and the bridge-local
restore/cooldowns-path/pooled-ids twins were deleted after the flip
(proven equivalent, same log lines). Browser imports stay lazy inside
`do_connect_page_pool` (fault tolerance + panels never import browser
at top level). Imports go panels -> services/core only.
"""

import json
import re

from app.core.cooldown import clamp_seconds, config_to_dict, format_remaining
from app.persistence.cooldown_store import save_entries
from app.services.cooldown_service import (
    edit_cooldown,
    force_reset_page,
    is_stuck_status,
    load_config,
    refresh_expired,
    request_tab_abort,
    reset_cooldown,
    tab_has_live_job,
)
from app.services.run_state import cooldowns_path, restore_page_state
from app.ui.qt_compat import Slot


def reset_pool_dicts(pool) -> None:
    """Empty pool internals (best effort)."""
    try:
        pool._pages.clear()
        pool._clients.clear()
        pool._controllers.clear()
    except Exception:
        pass


def reset_stuck_page(bridge, tab_id: str, page) -> str:
    """Force-free a stuck page; refuses while its own job is alive."""
    was = getattr(page.status, "value", page.status)
    if tab_has_live_job(bridge._page_pool, tab_id):
        bridge._log(f"⚠ Reset refused for {(tab_id or '')[:12]} — job still running on this tab; stop it first", "warn")
        return json.dumps({"ok": False, "error": "job still running on this tab — stop it first"})
    if force_reset_page(bridge._page_pool, tab_id):
        bridge._emit_pool_status()
        bridge._log(f"♻️ Stuck {was} reset for {(tab_id or '')[:12]} (no run active) — tab ready, fix and run again", "success")
        return json.dumps({"ok": True})
    return json.dumps({"ok": False, "error": "unknown tab"})


async def connect_pool_client(bridge, ws_url: str):
    """CDP client for a pool join (None + error log when refused)."""
    from app.browser.cdp_client import CDPClient
    host = bridge._page_pool._host if bridge._page_pool else "127.0.0.1"
    port = bridge._page_pool._port if bridge._page_pool else 9222
    client = CDPClient(host=host, port=port)
    if await client.connect(ws_url):
        return client
    bridge._log(f"❌ Pool connect failed {ws_url[:80]}", "error")
    return None


def finish_pool_join(bridge, info, client, ctrl) -> None:
    """Register a joined tab: page + client, restore timers, announce."""
    bridge._page_pool.add_page(info)
    bridge._page_pool.register_client(info.tab_id, client, ctrl)
    restore_page_state(bridge, info.tab_id)
    bridge._emit_pool_status()
    total, free = bridge._page_pool.get_counts()
    bridge._log(f"✅ Pool added {info.tab_id[:12]} steady — {info.title[:40]} — total {total} free {free}", "success")
    if total >= 2:
        bridge._log(f"✅ {total} tabs in pool ready for parallel — 2+ images will dispatch to different webpages", "success")


async def do_connect_page_pool(bridge, ws_url: str):
    """Attach one Chrome tab to the pool (client + controller + restore)."""
    try:
        from app.browser.cdp_arena import CDPArenaController
        from app.browser.page_status import PageInfo
        m = re.search(r'/devtools/page/([^/]+)$', ws_url)
        tab_id = m.group(1) if m else ws_url
        client = await connect_pool_client(bridge, ws_url)
        if client is None:
            return
        ctrl = CDPArenaController(client, log_callback=lambda msg: bridge._log(msg, "info"))
        live_title, live_url = await bridge._resolve_tab_info(tab_id, ws_url)
        info = PageInfo(tab_id=tab_id, ws_url=ws_url, title=live_title or tab_id, url=live_url or "")
        finish_pool_join(bridge, info, client, ctrl)
    except Exception as e:
        bridge._log(f"Pool connect exception {e}", "error")


class PagePoolMixin:
    """Pooled-tab management and cooldown config/control slots."""

    @Slot(result=str)
    def get_page_pool_status(self):
        try:
            if not self._page_pool:
                return json.dumps({"total": 0, "steady": 0, "busy": 0, "cooling": 0, "free": 0, "pages": []})
            try:
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
            reset_pool_dicts(self._page_pool)
            try:
                save_entries(cooldowns_path(self), {})
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
            self._schedule_coro(do_connect_page_pool(self, ws_url))
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
    def get_cooldown_config(self):
        try:
            cfg = load_config(self.config.get_state)
            return json.dumps({"ok": True, "config": config_to_dict(cfg)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def set_cooldown_config(self, cfg_json: str):
        try:
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
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            page = self._page_pool.get_page(tab_id)
            if page is None:
                return json.dumps({"ok": False, "error": "unknown tab"})
            if is_stuck_status(page.status):
                return reset_stuck_page(self, tab_id, page)
            if reset_cooldown(self._page_pool, tab_id):
                self._emit_pool_status()
                self._log(f"♻️ Cooldown reset for {(tab_id or '')[:12]} — tab ready", "success")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "unknown tab"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def stop_tab_job(self, tab_id: str):
        """Abort the live job on this tab; it fails as Aborted."""
        try:
            if request_tab_abort(self._page_pool, tab_id):
                self._log(f"⛔ Stop requested for job on {(tab_id or '')[:12]}", "warn")
                self._emit_pool_status()
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "no live job on this tab"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, int, result=str)
    def set_page_cooldown(self, tab_id: str, seconds: int):
        try:
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
