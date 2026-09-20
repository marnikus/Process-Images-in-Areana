"""Browser tabs panel — CDP tab list/diagnose/auto-scan/popup/primary/connect/find.

ideal-size(reason): 7-slot tab surface plus async phase splits — connect, find
and diagnose each exceed 20 LOC / CC 7 as one function, so phases live beside
their single callers per RULE 16; splitting the file would scatter
slot+phase pairs. Reuses single-source url_queue/page_pool funcs via acyclic
sibling imports (those panels never import back). Browser imports stay lazy
(fault tolerance, R5/R6 precedent); services/utils hoisted (no cycle:
services never import ui).
"""

import asyncio
import json
import logging
import re
import time

from app.services.auto_connect import live_tab_keys, pick_primary_ws, plan_auto_connect, prunable_row_ids, sync_pool_presence
from app.services.run_state import pooled_ids, resolve_tab_info, restore_page_state, schedule_coro
from app.ui.panels.page_pool import do_connect_page_pool
from app.ui.panels.url_queue import _add_missing_rows, _dedupe_state_rows
from app.ui.qt_compat import Slot
from app.utils.win_popup import raise_window_titles

log = logging.getLogger("arena")


def claim_connect_slot(bridge, ws_url: str) -> bool:
    """Debounce same-ws reconnects (1.5s / in-progress); True to proceed."""
    try:
        now = time.time()
        if ws_url == bridge._last_connect_ws and (now - bridge._last_connect_ts) < 1.5:
            log.debug(f"connect_tab debounced duplicate {ws_url[:60]}")
            return False
        if bridge._connect_in_progress and ws_url == bridge._last_connect_ws:
            log.debug(f"connect_tab already in progress for {ws_url[:60]}, skipping")
            return False
        bridge._last_connect_ws = ws_url
        bridge._last_connect_ts = now
    except Exception:
        pass
    return True


async def connect_reused(bridge, ws_url: str) -> bool:
    """True when already on this tab (announced, nothing to do)."""
    try:
        if bridge.cdp and bridge.cdp.is_connected and bridge.cdp._current_tab_id:
            m = re.search(r'/devtools/page/([^/]+)$', ws_url)
            if m and m.group(1) == bridge.cdp._current_tab_id:
                bridge._log(f"✅ Already connected to {ws_url[:80]} (reuse)", "success")
                bridge.connection_status.emit("connected")
                return True
    except Exception:
        pass
    return False


def cached_tab_identity(bridge, ws_url: str):
    """(tab_id, title, url) from the URL + cached cdp attrs."""
    m_id = re.search(r'/devtools/page/([^/]+)$', ws_url)
    tab_id = m_id.group(1) if m_id else getattr(bridge.cdp, '_current_tab_id', '') or ws_url
    title = getattr(bridge.cdp, '_current_title', '') or ''
    url = getattr(bridge.cdp, '_current_url', '') or ''
    return tab_id, title, url


async def pool_tab_identity(bridge, ws_url: str):
    """(tab_id, title, url) for the connected tab, live-resolved."""
    tab_id, title, url = cached_tab_identity(bridge, ws_url)
    if not url or not title:
        live_title, live_url = await resolve_tab_info(bridge, tab_id, ws_url)
        title = title or live_title or tab_id
        url = url or live_url
    return tab_id, title, url


def announce_tab_connected(bridge, ws_url: str) -> None:
    """Success logs + status for a fresh connection."""
    bridge._log(f"✅ Connected to {ws_url[:80]} (tab {bridge.cdp._current_tab_id[:20]}…)", "success")
    bridge.connection_status.emit("connected")
    bridge._log(f"CDP session active on ws://{bridge.cdp._host}:{bridge.cdp._port}/devtools/page/{bridge.cdp._current_tab_id[:30]}", "info")


def reuse_pool_page(bridge, identity) -> None:
    """Pool already holds a live dedicated client: refresh info only."""
    from app.browser.page_status import PageInfo
    tab_id, ws_url, title, url = identity
    bridge._page_pool.add_page(PageInfo(tab_id=tab_id, ws_url=ws_url, title=title, url=url))
    bridge._emit_pool_status()
    bridge._log(f"📦 Pool: tab {tab_id[:12]} already has dedicated client steady (reuse)", "info")


async def add_dedicated_pool_page(bridge, identity) -> None:
    """Pool-join with an independent per-tab client (parallel-safe)."""
    from app.browser.page_status import PageInfo
    from app.browser.cdp_arena import CDPArenaController
    from app.browser.cdp_client import CDPClient
    tab_id, ws_url, title, url = identity
    host = getattr(bridge.cdp, '_host', '127.0.0.1')
    port = getattr(bridge.cdp, '_port', 9222)
    dedicated = CDPClient(host=host, port=port)
    if not await dedicated.connect(ws_url):
        add_fallback_pool_page(bridge, identity)
        return
    bridge._page_pool.add_page(PageInfo(tab_id=tab_id, ws_url=ws_url, title=title, url=url))
    ctrl2 = CDPArenaController(dedicated, log_callback=lambda m: bridge._log(m, "info"))
    bridge._page_pool.register_client(tab_id, dedicated, ctrl2)
    bridge._emit_pool_status()
    total, free = bridge._page_pool.get_counts()
    bridge._log(f"📦 Pool: added tab {tab_id[:12]} steady with dedicated client — total {total} pages {free} free", "success")
    if total >= 2:
        bridge._log(f"✅ {total} tabs in pool ready for parallel — when 2+ images selected, Run will dispatch to different webpages (steady/busy tracked, no double-send)", "success")


def add_fallback_pool_page(bridge, identity) -> None:
    """Pool-join reusing the primary client (dedicated connect failed)."""
    from app.browser.page_status import PageInfo
    from app.browser.cdp_arena import CDPArenaController
    tab_id, ws_url, title, url = identity
    bridge._page_pool.add_page(PageInfo(tab_id=tab_id, ws_url=ws_url, title=title, url=url))
    ctrl = CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
    bridge._page_pool.register_client(tab_id, bridge.cdp, ctrl)
    bridge._emit_pool_status()
    total_f, _ = bridge._page_pool.get_counts() if bridge._page_pool else (0, 0)
    bridge._log(f"📦 Pool: added primary tab {tab_id[:12]} steady (dedicated failed, using primary) — total {total_f}", "warn")


async def attach_connected_tab(bridge, ws_url: str) -> None:
    """Pool-join the fresh connection (reuse / dedicated / fallback).

    Dedicated per-tab client: pool tabs must not share one websocket.
    """
    try:
        if not bridge._page_pool:
            return
        tab_id, title, url = await pool_tab_identity(bridge, ws_url)
        existing_client, _ = bridge._page_pool.get_clients(tab_id)
        if existing_client and getattr(existing_client, 'is_connected', False):
            reuse_pool_page(bridge, (tab_id, ws_url, title, url))
        else:
            await add_dedicated_pool_page(bridge, (tab_id, ws_url, title, url))
            restore_page_state(bridge, tab_id)  # else-only: reuse changes nothing
    except Exception as e:
        import traceback as _tb
        bridge._log(f"Pool add primary failed: {e} {_tb.format_exc()[-500:]}", "warn")


async def do_connect_tab(bridge, ws_url: str) -> None:
    """Connect + pool-join one tab (reuses live sessions)."""
    bridge._connect_in_progress = True
    try:
        if await connect_reused(bridge, ws_url):
            return
        if await bridge.cdp.connect(ws_url):
            announce_tab_connected(bridge, ws_url)
            await attach_connected_tab(bridge, ws_url)
        else:
            bridge._log(f"❌ Connect failed for {ws_url[:120]} — check Chrome still open on port {bridge.cdp._port}, try Diagnose", "error")
            bridge._log(f"💡 Tip: Ensure Chrome was started with --remote-debugging-port={bridge.cdp._port} --user-data-dir=... and that http://{bridge.cdp._host}:{bridge.cdp._port}/json/list shows JSON in browser", "warn")
            bridge.connection_status.emit("error")
    except Exception as e:
        import traceback
        bridge._log(f"❌ Connect exception for {ws_url[:80]}: {e} — {traceback.format_exc()[-1000:]}", "error")
        bridge.connection_status.emit("error")
    finally:
        bridge._connect_in_progress = False


def find_dupe_recent(bridge, q: str, now: float) -> bool:
    """True when q matches the last find inside the 1.0s window."""
    return bool(q) and q == bridge._last_find_query and (now - bridge._last_find_ts) < 1.0


def claim_find_slot(bridge, query: str):
    """Normalize + debounce tab-find (1.0s / in-progress); None = debounced."""
    try:
        now = time.time()
        q = (query or "").strip()
        if find_dupe_recent(bridge, q, now):
            log.debug(f"find_tab_by_url debounced duplicate {q[:60]}")
            return None
        if bridge._find_in_progress:
            log.debug(f"find_tab_by_url already in progress, skipping {q[:60]}")
            return None
        bridge._last_find_query = q
        bridge._last_find_ts = now
        return q
    except Exception:
        return (query or "").strip()


async def report_no_tabs(bridge, query: str) -> None:
    """Diagnose an empty tab list (executor diag + fix tip), answer []."""
    try:
        loop = asyncio.get_event_loop()
        diag = await loop.run_in_executor(None, lambda: bridge.cdp.diagnose_sync())
        bridge._log(diag.get("summary", "⚠ No Chrome tabs found"), "warn")
        bridge._log(f"💡 Fix: 1) Close ALL Chrome windows. 2) Run: \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --remote-debugging-port={bridge.cdp._port} --user-data-dir=\"C:\\arena-images-chrome\" 3) Open https://arena.ai in that NEW Chrome window. 4) Click Diagnose. 5) Open http://{bridge.cdp._host}:{bridge.cdp._port}/json/list — you should see JSON.", "warn")
    except Exception:
        bridge._log(f"⚠ No Chrome tabs found — start Chrome with --remote-debugging-port={bridge.cdp._port} --user-data-dir=\"C:\\arena-images-chrome\"", "warn")
    bridge.tab_match_result.emit(query, "[]")


def report_tab_matches(bridge, query: str, tabs) -> None:
    """Best-match tabs, log top-3, answer the match result."""
    from app.browser.tab_matcher import best_matches
    tab_dicts = [{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs]
    matches = best_matches(query, tab_dicts)
    if not matches:
        bridge._log(f"❌ No tab matches “{query}”. Available: " + "; ".join(f"{t.title} — {t.url}" for t in tabs[:5]), "error")
        bridge.tab_match_result.emit(query, "[]")
        return
    for m in matches[:3]:
        bridge._log(f"  · match ({m['kind']}): {m['title']} — {m['url']}", "success")
    bridge.tab_match_result.emit(query, json.dumps(matches, ensure_ascii=False))


async def match_live_tabs(bridge, query: str) -> None:
    """Fetch tabs; route to no-tabs / no-match / matches reporting."""
    tabs = await bridge.cdp.fetch_tabs()
    if not tabs:
        await report_no_tabs(bridge, query)
        return
    report_tab_matches(bridge, query, tabs)


async def do_find_tab(bridge, query: str) -> None:
    """Match live tabs against the query (debounced by the slot)."""
    bridge._find_in_progress = True
    try:
        query = (query or "").strip()
        if not query:
            bridge._log("⚠ URL field empty", "warn")
            bridge.tab_match_result.emit(query, "[]")
            return
        try:
            await match_live_tabs(bridge, query)
        except Exception as e:
            bridge._log(f"❌ Tab matching failed: {e}", "error")
            bridge.tab_match_result.emit(query, "[]")
    finally:
        bridge._find_in_progress = False


async def do_fetch_tabs(bridge) -> None:
    """Fetch live tabs; an empty list also drops a diagnose summary."""
    try:
        tabs = await bridge.cdp.fetch_tabs()
        payload = json.dumps([{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs], ensure_ascii=False)
        bridge.tabs_received.emit(payload)
        if not tabs:
            try:
                loop = asyncio.get_event_loop()
                diag = await loop.run_in_executor(None, lambda: bridge.cdp.diagnose_sync())
                bridge._log(diag.get("summary", ""), "warn")
            except Exception:
                pass
    except Exception as e:
        bridge._log(f"❌ Tab fetch failed: {e}", "error")


def report_diag_checks(bridge, diag) -> None:
    """Per-host port state + first tabs of each check."""
    for chk in diag.get("checks", []):
        host = chk.get("host")
        if chk.get("port_open"):
            bridge._log(f"  · {host}:{bridge.cdp._port} open — list: {chk.get('list_count')} tabs", "info")
        else:
            bridge._log(f"  · {host}:{bridge.cdp._port} closed — {chk.get('list_error') or chk.get('version_error') or 'no response'}", "warn")
        for t in chk.get("tabs", [])[:5]:
            bridge._log(f"    - {t.get('title', '')[:60]} — {t.get('url', '')}", "success")


async def do_diagnose_chrome(bridge) -> None:
    """Executor-diagnose Chrome; summary + checks + tabs to the UI."""
    try:
        loop = asyncio.get_event_loop()
        diag = await loop.run_in_executor(None, lambda: bridge.cdp.diagnose_sync())
        bridge._log(diag.get("summary", ""), "info" if "✅" in diag.get("summary", "") else "warn")
        report_diag_checks(bridge, diag)
        if diag.get("tabs"):
            try:
                payload = json.dumps([{"id": t.get("id"), "title": t.get("title"), "url": t.get("url"), "ws_url": t.get("ws_url")} for t in diag.get("tabs", [])], ensure_ascii=False)
                bridge.tabs_received.emit(payload)
            except Exception:
                pass
    except Exception as e:
        bridge._log(f"Diagnose failed: {e}", "error")


def live_deps(bridge):
    """Wiring for the Python-owned reconciler (S6)."""
    async def fetch_tabs(): return await bridge.cdp.fetch_tabs()
    async def join_tab(ws_url): await do_connect_page_pool(bridge, ws_url)
    def commit():
        bridge._save_arena(); bridge._emit_arena_state()
        try:
            from app.services.live.bus import live_bus
            live_bus(bridge).wake("urls")
        except Exception: pass
    def log(msg):
        try: bridge._log(msg, "info")
        except Exception: pass
    try:
        from app.services.live.reconcile import LiveDeps as LD
        return LD(fetch_tabs=fetch_tabs, join_tab=join_tab, commit=commit, log=log)
    except Exception: return None


def start_url_reconciler(bridge) -> None:
    """Boot-time start for the reconciler loop (S6)."""
    try:
        deps = live_deps(bridge)
        if deps is None:
            return
        from app.services.live.reconcile import start_reconciler
        start_reconciler(bridge, deps)
    except Exception:
        pass


def prune_auto_rows(bridge, plan) -> int:
    """Drop auto-linked rows whose tabs vanished; returns removed count."""
    if not plan.remove:
        return 0
    gone = set(plan.remove)
    before = len(bridge.state.urls)
    bridge.state.urls = [u for u in bridge.state.urls if u.id not in gone]
    return before - len(bridge.state.urls)


def claim_auto_rows(by_id, claims) -> bool:
    """Link unlinked rows to their tabs; True when any row changed."""
    changed = False
    for row_id, tab_id in claims:
        row = by_id.get(row_id)
        if row is not None and not row.tab_id:
            row.tab_id = tab_id
            changed = True
    return changed


def apply_auto_plan(bridge, plan) -> bool:
    """Claim/add/prune URL rows from the plan; True when rows changed."""
    by_id = {u.id: u for u in bridge.state.urls}
    changed = claim_auto_rows(by_id, plan.claim)
    added = _add_missing_rows(bridge.state.urls, plan.add)
    pruned = prune_auto_rows(bridge, plan)
    changed = bool(added) or changed or pruned > 0
    if changed:
        bridge._save_arena()
        bridge._emit_arena_state()
    return changed


def plan_has_changes(plan, revived, stale) -> bool:
    """True when the scan produced rows/joins/presence changes to report."""
    return any((plan.add, plan.claim, plan.connect, revived, stale, plan.remove))


def report_auto_plan(bridge, plan, presence, source) -> None:
    """Pool emit + summary; manual scans always answer, auto only on change."""
    revived, stale = presence
    if not plan_has_changes(plan, revived, stale):
        if source == "manual":
            bridge._log("🤖 Reparse: no changes — rows and pool already match open tabs", "info")
        return
    if plan.connect or revived or stale or plan.remove:
        bridge._emit_pool_status()
    bridge._log(f"🤖 Auto-connect: +{len(plan.add)} rows, {len(plan.claim)} linked, "
                f"{len(plan.connect)} joined, {revived} revived, {len(stale)} stale, "
                f"{len(plan.remove)} removed", "info")


async def join_new_tabs(bridge, sockets) -> None:
    """Pool-join each connectable tab; skips empty sockets."""
    for ws in sockets or []:
        if ws:
            await do_connect_page_pool(bridge, ws)


def auto_prune_allowed(bridge, tabs) -> bool:
    """Prune dead rows only with a healthy tab list and no live run."""
    if getattr(bridge, "_run_state", "idle") != "idle":
        return False
    return any(getattr(t, "id", "") or getattr(t, "ws_url", "") for t in tabs or [])


def plan_auto_sync(bridge, tabs, pattern, rows):
    """Plan the scan; attach safe row pruning when allowed."""
    plan = plan_auto_connect(tabs, pattern, rows, pooled_ids(bridge._page_pool))
    if auto_prune_allowed(bridge, tabs):
        plan.remove = prunable_row_ids(rows, live_tab_keys(tabs))
    return plan


async def auto_scan_pass(bridge, source: str) -> None:
    """Delegation to the Python-owned reconciler (S6)."""
    from app.services.live.reconcile import reconcile_once
    await reconcile_once(bridge, live_deps(bridge), source)


async def do_auto_connect_scan(bridge, source: str = "auto") -> None:
    """Fetch tabs, sync rows + pool + presence; skips when busy."""
    if bridge._auto_scan_running:
        return
    bridge._auto_scan_running = True
    try:
        await auto_scan_pass(bridge, source)
    except Exception as e:
        bridge._log(f"Auto-connect scan skipped: {e}", "warn")
    finally:
        bridge._auto_scan_running = False


def popup_row_title(pool, seen, u):
    """Live title for the row (None when skipped); claims tab_id in seen."""
    if not (u.enabled and u.tab_id) or u.tab_id in seen:
        return None
    page = pool.get_page(u.tab_id)
    if page is None or not page.is_connected:
        return None
    seen.add(u.tab_id)
    return page.title or None


def popup_targets(bridge) -> list:
    """Titles of enabled rows with live pool tabs (deduped)."""
    titles = []
    try:
        pool = bridge._page_pool
        if not pool:
            return titles
        seen = set()
        for u in bridge.state.urls:
            title = popup_row_title(pool, seen, u)
            if title is not None:
                titles.append(title)
    except Exception:
        pass
    return titles


async def do_popup_url_tabs(bridge) -> None:
    """Raise desktop windows of live URL tabs (no tab switching)."""
    targets = popup_targets(bridge)
    if not targets:
        bridge._log("⏫ Popup: no active URL tabs (need enabled + linked + connected)", "warn")
        return
    try:
        raised = raise_window_titles(targets)
    except Exception:
        raised = 0
    bridge._log(f"⏫ Popup: {raised}/{len(targets)} windows on top (tabs untouched)", "success")


def primary_ws(bridge) -> str:
    """Socket of the first live pool tab, else ''."""
    try:
        pages = list(bridge._page_pool._pages.values()) if bridge._page_pool else []
        return pick_primary_ws(pages)
    except Exception:
        return ""


async def do_ensure_primary(bridge) -> None:
    """Passive primary retry: connect first live pool tab when down."""
    try:
        if not bridge.cdp or bridge.cdp.is_connected or bridge._ensure_running:
            return
        bridge._ensure_running = True
        try:
            ws = primary_ws(bridge)
            if ws and await bridge.cdp.connect(ws):
                bridge._log("✅ Primary auto-connected — runs can start", "success")
                bridge.connection_status.emit("connected")
        finally:
            bridge._ensure_running = False
    except Exception:
        pass


class BrowserTabsMixin:
    """CDP tab slots: list, diagnose, auto-scan, popup, primary, connect, find."""

    @Slot(result=str)
    def get_tabs(self):
        """Non-blocking: always schedule async fetch in thread, return pending immediately.
        Previous sync fetch_tabs_sync did blocking DNS/socket in UI thread causing freeze.
        """
        if not self.cdp:
            return json.dumps([], ensure_ascii=False)
        # Schedule async fetch in background thread, return pending instantly
        schedule_coro(self, do_fetch_tabs(self))
        return "pending"

    @Slot(result=str)
    def diagnose_chrome(self):
        """Non-blocking diagnose: schedule in thread, return pending, emit logs via signals.
        Previous sync version blocked UI for several seconds doing DNS + socket checks.
        """
        if not self.cdp:
            return json.dumps({"error": "CDP not available"}, ensure_ascii=False)
        self._log(f"🩺 Diagnosing Chrome remote debugging on {self.cdp._host}:{self.cdp._port}… (non-blocking)", "info")
        schedule_coro(self, do_diagnose_chrome(self))
        return "pending"

    @Slot(str, result=str)
    def auto_connect_scan(self, source: str):
        """Non-blocking auto-connect scan: rows + pool follow open tabs."""
        if not self.cdp or not self._page_pool:
            return json.dumps({"ok": False, "error": "CDP or pool not ready"})
        if self._auto_scan_running:
            return "pending"
        schedule_coro(self, do_auto_connect_scan(self, source or "auto"))
        return "pending"

    @Slot(result=str)
    def popup_url_tabs(self):
        """Popup-on-top: raise OS windows of live URL tabs, tabs untouched."""
        if not self._page_pool:
            return json.dumps({"ok": False, "error": "pool not initialized"})
        schedule_coro(self, do_popup_url_tabs(self))
        return "pending"

    @Slot(result=str)
    def ensure_primary_connected(self):
        """500ms passive tick: keep the primary tab connected."""
        if not self.cdp:
            return json.dumps({"ok": False})
        try:
            if self.cdp.is_connected:
                return json.dumps({"ok": True})
        except Exception:
            pass
        schedule_coro(self, do_ensure_primary(self))
        return "pending"

    @Slot(str)
    def connect_tab(self, ws_url: str):
        if not self.cdp:
            self._log("CDP client not available", "error")
            return
        if not claim_connect_slot(self, ws_url):
            return
        self._log(f"🔗 Connecting to {ws_url[:120]}… (port {self.cdp._port}, host {self.cdp._host})", "info")
        schedule_coro(self, do_connect_tab(self, ws_url))

    @Slot(str)
    def find_tab_by_url(self, query: str):
        """Non-blocking: schedule async matching in thread with debounce."""
        if not self.cdp:
            self._log("CDP not available", "error")
            return
        q = claim_find_slot(self, query)
        if q is None:
            return
        schedule_coro(self, do_find_tab(self, q))
