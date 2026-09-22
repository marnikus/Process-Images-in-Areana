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
from app.services import tab_reset
from app.services.cooldown_service import (
    edit_cooldown,
    load_config,
    refresh_expired,
)
from app.services.live.bus import live_bus
from app.services.live.tab_owner import resolve_owners
from app.services.live.worker_badges import assert_badges, clear_badge
from app.services.run_state import (
    cooldowns_path,
    resolve_tab_info,
    restore_page_state,
    schedule_coro,
    tab_label_of,
)
from app.ui.qt_compat import Slot


def reset_pool_dicts(pool) -> None:
    """Empty pool internals (best effort)."""
    try:
        pool._pages.clear()
        pool._clients.clear()
        pool._controllers.clear()
    except Exception:
        pass


def join_handle(bridge, ws_url: str):
    """The handle a pool join works from — its own endpoint, not the pool's (round 9).

    A pooled row can come from any enabled browser; the handle names which endpoint it is
    on, so the join attaches there instead of to whichever browser happens to be active.
    """
    from app.browser import attached
    pool = getattr(bridge, "_page_pool", None)
    host = getattr(pool, "_host", "127.0.0.1") or "127.0.0.1"
    port = getattr(pool, "_port", 9222) or 9222
    return attached.parse_handle(ws_url, host, port)


def _scan_rows(bridge) -> tuple:
    """(settings rows, base port) for naming a handle's owner — lazily, panels stay thin."""
    from app.ui.panels.browser_tabs import scan_settings
    rows, base, _host = scan_settings(bridge)
    return rows, base


async def connect_pool_client(bridge, ws_url: str):
    """A client attached to this tab's own endpoint (None + a named reason when refused)."""
    from app.browser import attached
    from app.browser.cdp_client import CDPClient
    handle = join_handle(bridge, ws_url)
    refusal = attached.refusal(handle, "connect")
    if refusal:
        bridge._log(f"❌ {refusal}", "warn")
        return None
    client = CDPClient(host=handle.host, port=handle.port, protocol=handle.channel)
    if await client.connect(ws_url):
        return client
    bridge._log(f"❌ Pool connect failed {ws_url[:80]}", "error")
    return None


async def finish_pool_join(bridge, info, client, ctrl) -> None:
    """Register a joined tab: page + client, restore timers, badge the tab, announce."""
    bridge._page_pool.add_page(info)
    bridge._page_pool.register_client(info.tab_id, client, ctrl)
    restore_page_state(bridge, info.tab_id)
    await resolve_owners(bridge._page_pool)  # `{email}_{4 digits}` before the badge (D-5)
    await assert_badges(bridge._page_pool)   # `#n + label` on the tab, right away (D-5)
    bridge._emit_pool_status()               # persists the number with the timers (D0-2)
    total, free = bridge._page_pool.get_counts()
    label = tab_label_of(bridge._page_pool, info.tab_id)
    bridge._log(f"✅ Pool added {label} steady — {info.title[:40]} — total {total} free {free}", "success")
    if total >= 2:
        bridge._log(f"✅ {total} tabs in pool ready for parallel — 2+ images will dispatch to different webpages", "success")


def leave_pool(bridge, tab_id: str) -> bool:
    """Badge off (client captured *before* the pool forgets it), then the page leaves."""
    client, _ctrl = bridge._page_pool.get_clients(tab_id)
    if client is not None:
        schedule_coro(bridge, clear_badge(client, tab_id))
    return bridge._page_pool.remove_page(tab_id)


def _sockets_by_tab(tabs) -> dict:
    """Fetched tabs as {tab key: ws url} in one expression (no statement nesting)."""
    return {(getattr(t, "id", "") or getattr(t, "tab_id", "")): (getattr(t, "ws_url", "") or "")
            for t in tabs or []}


async def _live_sockets(bridge) -> dict:
    """Every enabled browser's tabs right now — the panel's one-pass listing.

    Round 9: the pass is the whole settings window (Chrome + Firefox + Edge at their own
    endpoints, each over its own channel), so a re-checked Firefox row rejoins through the
    same map a Chrome row does. {} when the pass fails — a rejoin is never a removal.
    """
    try:
        from app.ui.panels.browser_tabs import live_tab_rows
        return _sockets_by_tab(await live_tab_rows(bridge))
    except Exception:
        return {}


async def _rejoin_one(bridge, pool, sockets: dict, tab_id: str) -> bool:
    """Join one re-checked row's tab (False when it is pooled already or no longer open)."""
    if pool.get_page(tab_id):
        return False
    ws = sockets.get(tab_id, "")
    if not ws:
        bridge._log(f"♻️ Rejoin skipped for {(tab_id or '')[:12]} — tab is not open; the next pass drops the row", "warn")
        return False
    await do_connect_page_pool(bridge, ws)  # same mechanic as the reconciler: badge + cooldown restored
    return True


async def rejoin_checked_rows(bridge, tab_ids) -> int:
    """The join half of the checkbox gate (I-56): re-checked rows' tabs rejoin at once.

    One fetch for the whole batch; the reconciler pass stays the fallback for a
    tab Chrome had not listed yet. Returns how many tabs actually joined.
    """
    pool = getattr(bridge, "_page_pool", None)
    if pool is None or not tab_ids:
        return 0
    sockets = await _live_sockets(bridge)
    joined = 0
    for tab_id in tab_ids:
        joined += 1 if await _rejoin_one(bridge, pool, sockets, tab_id) else 0
    if joined:
        live_bus(bridge).wake("urls")  # a live run picks the worker up on its next pass
    return joined


async def own_tab_info(bridge, handle, client) -> tuple:
    """(title, url) from the tab's own endpoint — what the pool row's label is built from.

    A pooled tab can belong to any enabled browser, so the list that knows its title is the
    one from the endpoint the handle names, over the channel it names (`client.fetch_tabs`
    routes by protocol). When that endpoint cannot answer, the active browser's list is the
    fallback — and the tab id still labels the row.
    """
    from app.browser import attached
    rows = []
    try:
        rows = await client.fetch_tabs() or []
    except Exception:
        rows = []
    for row in rows:
        if attached.row_key(row) == handle.tab_id:
            return getattr(row, "title", "") or "", getattr(row, "url", "") or ""
    return await resolve_tab_info(bridge, handle.tab_id, handle.ws_url)


def pool_page_info(bridge, handle, title: str, url: str):
    """The pool's row for a joined tab — its own label, endpoint and browser (round 9)."""
    from app.browser import attached
    from app.browser.page_status import PageInfo
    rows, base = _scan_rows(bridge)
    return PageInfo(tab_id=handle.tab_id, ws_url=handle.ws_url, title=title or handle.tab_id,
                    url=url or "", browser=attached.owner_of(handle, rows, base))


async def do_connect_page_pool(bridge, ws_url: str):
    """Attach one tab to the pool (client + controller + restore) — any browser's channel."""
    try:
        from app.browser.cdp_arena import CDPArenaController
        handle = join_handle(bridge, ws_url)
        client = await connect_pool_client(bridge, ws_url)
        if client is None:
            return
        ctrl = CDPArenaController(client, log_callback=lambda msg: bridge._log(msg, "info"))
        title, url = await own_tab_info(bridge, handle, client)
        await finish_pool_join(bridge, pool_page_info(bridge, handle, title, url), client, ctrl)
    except Exception as e:
        import traceback
        bridge._log(f"Pool connect exception {e} — {traceback.format_exc()[-800:]}", "error")


class PagePoolMixin:
    """Pooled-tab management and cooldown config/control slots.

    ideal-size: 9 frozen JS slots; validate/wire helpers already live at
    module level — remaining per-slot bodies cannot move without
    scattering slot+helper pairs (R10.10).
    """

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
            # An explicit Connect is the user asking for one more try at a parked Firefox
            # (round 11, D-6): the auto passes never re-ask, this one may.
            from app.ui.panels.browser_tabs import retry_firefox
            retry_firefox(self)
            self._log(f"🔗 Adding tab to pool {ws_url[:80]}… steady", "info")
            schedule_coro(self, do_connect_page_pool(self, ws_url))
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def disconnect_page_pool(self, tab_id: str):
        try:
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            ok = leave_pool(self, tab_id)
            self._emit_pool_status()
            if ok:
                pool = getattr(self, "_page_pool", None)
                self._log(f"Pool page {tab_label_of(pool, tab_id)} removed", "info")
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
        """Clear time (D-5): the pause goes, the row is ready — and the reply says
        exactly what was removed, so the row can show it."""
        return json.dumps(tab_reset.clear_time(self, tab_id), ensure_ascii=False)

    @Slot(str, result=str)
    def stop_tab_job(self, tab_id: str):
        """Stop (D-3): abort a live job, or repair a tab no run owns any more."""
        return json.dumps(tab_reset.stop_request(self, tab_id), ensure_ascii=False)

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
