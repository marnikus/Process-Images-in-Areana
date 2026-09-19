"""Cdp Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import asyncio
import json
import logging
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

from app.browser.tab_matcher import best_matches

log = logging.getLogger("arena")

from app.ui.panels._bridge_helpers import _dedupe_state_rows
from app.ui.panels._bridge_helpers import _add_missing_rows

class CdpLoopPanel:

    def _ensure_bg_loop(self):
        """Ensure a background event loop thread exists and is running."""
        try:
            bg_loop = getattr(self, '_bg_loop', None)
            if bg_loop and bg_loop.is_running():
                return bg_loop
            self._bg_ensure_primitives()
            with self._bg_lock:
                bg_loop = getattr(self, '_bg_loop', None)
                if bg_loop and bg_loop.is_running():
                    return bg_loop
                self._bg_start_locked()
            try:
                self._bg_ready.wait(timeout=5)
            except Exception:
                pass
            return getattr(self, '_bg_loop', None)
        except Exception as e:
            import traceback
            log.warning(f"_ensure_bg_loop failed: {e} {traceback.format_exc()[-500:]}")
            return None

    def _bg_ensure_primitives(self):
        """Recreate _bg_lock/_bg_ready if missing or wrong type (old pickles)."""
        import threading
        if not isinstance(getattr(self, '_bg_lock', None), type(threading.Lock())):
            self._bg_lock = threading.Lock()
        if not isinstance(getattr(self, '_bg_ready', None), type(threading.Event())):
            self._bg_ready = threading.Event()

    def _bg_start_locked(self):
        """Start the bg loop thread (caller holds _bg_lock)."""
        import threading
        try:
            self._bg_ready.clear()
        except Exception:
            self._bg_ready = threading.Event()
        t = threading.Thread(target=self._bg_run_loop, daemon=True, name="arena-bg-loop")
        t.start()
        self._bg_thread = t

    def _bg_run_loop(self):
        """Thread body: fresh event loop, signal ready, run forever."""
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._bg_loop = loop
            try:
                self._bg_ready.set()
            except Exception:
                pass
            loop.run_forever()
        except Exception as e:
            log.warning(f"bg loop crashed: {e}")
            try:
                self._bg_ready.set()
            except Exception:
                pass

    def _schedule_coro(self, coro):
        """Schedule coro on persistent background loop via run_coroutine_threadsafe.
        This keeps CDP websocket receive loop alive after connect, unlike short-lived asyncio.run.
        Non-blocking for UI thread.
        """
        try:
            import asyncio
            loop = self._ensure_bg_loop()
            if loop and loop.is_running():
                return self._coro_on_loop(coro, loop)
            return self._coro_fallback_thread(coro)
        except Exception as e:
            log.warning(f"_schedule_coro failed: {e}")
            try:
                coro.close()
            except Exception:
                pass

    def _coro_on_loop(self, coro, loop):
        """run_coroutine_threadsafe + batch-future tracking + done callback."""
        import asyncio
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            # Heuristic: if coro is _do_run_batch, keep reference
            if hasattr(coro, 'cr_code') and coro.cr_code.co_name == '_do_run_batch':
                self._batch_future = future
        except Exception:
            pass
        future.add_done_callback(self._on_bg_future_done)
        return future

    def _on_bg_future_done(self, fut):
        """Done callback: log failures (skip cancels), clear _batch_future."""
        try:
            try:
                fut.result()
            except Exception as e:
                if self._is_cancel_error(e):
                    return
                log.warning(f"coro thread failed: {e}")
                try:
                    self._log(f"Async task failed: {e}", "error")
                except Exception:
                    pass
        finally:
            try:
                if self._batch_future is fut:
                    self._batch_future = None
            except Exception:
                pass

    @staticmethod
    def _is_cancel_error(e):
        """True when the future was cancelled (normal after user cancel)."""
        try:
            import concurrent.futures
            return isinstance(e, concurrent.futures.CancelledError)
        except Exception:
            return False

    def _coro_fallback_thread(self, coro):
        """Short-lived thread fallback when the bg loop is not available."""
        import asyncio
        import threading

        def _run():
            try:
                asyncio.run(coro)
            except Exception as e:
                log.warning(f"coro thread fallback failed: {e}")
                try:
                    self._log(f"Async task failed: {e}", "error")
                except Exception:
                    pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return None

    def _get_watcher_cdp_controller(self):
        """Get CDP controller for watcher — creates CDPArenaController from current cdp client."""
        try:
            if not self.cdp or not getattr(self.cdp, 'is_connected', False):
                return None
            from app.browser.cdp_arena import CDPArenaController
            return CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
        except Exception:
            return None


class TabsPanel:

    @Slot(result=str)
    def get_tabs(self):
        """Non-blocking: always schedule async fetch in thread, return pending immediately.
        Previous sync fetch_tabs_sync did blocking DNS/socket in UI thread causing freeze.
        """
        if not self.cdp:
            return json.dumps([], ensure_ascii=False)
        # Schedule async fetch in background thread, return pending instantly
        self._schedule_coro(self._do_fetch_tabs())
        return "pending"

    @Slot(result=str)
    def diagnose_chrome(self):
        """Non-blocking diagnose: schedule in thread, return pending, emit logs via signals.
        Previous sync version blocked UI for several seconds doing DNS + socket checks.
        """
        if not self.cdp:
            return json.dumps({"error": "CDP not available"}, ensure_ascii=False)
        self._log(f"🩺 Diagnosing Chrome remote debugging on {self.cdp._host}:{self.cdp._port}… (non-blocking)", "info")
        self._schedule_coro(self._do_diagnose_chrome())
        return "pending"

    async def _do_diagnose_chrome(self):
        try:
            # Run sync diagnose in threadpool to avoid blocking event loop
            import asyncio
            loop = asyncio.get_event_loop()
            diag = await loop.run_in_executor(None, lambda: self.cdp.diagnose_sync())
            self._log(diag.get("summary",""), "info" if "✅" in diag.get("summary","") else "warn")
            for chk in diag.get("checks", []):
                host = chk.get("host")
                if chk.get("port_open"):
                    self._log(f"  · {host}:{self.cdp._port} open — list: {chk.get('list_count')} tabs", "info")
                else:
                    self._log(f"  · {host}:{self.cdp._port} closed — {chk.get('list_error') or chk.get('version_error') or 'no response'}", "warn")
                for t in chk.get("tabs", [])[:5]:
                    self._log(f"    - {t.get('title','')[:60]} — {t.get('url','')}", "success")
            # Also emit tabs if found
            if diag.get("tabs"):
                try:
                    payload = json.dumps([{"id": t.get("id"), "title": t.get("title"), "url": t.get("url"), "ws_url": t.get("ws_url")} for t in diag.get("tabs", [])], ensure_ascii=False)
                    self.tabs_received.emit(payload)
                except Exception:
                    pass
        except Exception as e:
            err = f"Diagnose failed: {e}"
            self._log(err, "error")

    async def _do_fetch_tabs(self):
        try:
            tabs = await self.cdp.fetch_tabs()
            payload = json.dumps([{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs], ensure_ascii=False)
            self.tabs_received.emit(payload)
            if not tabs:
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    diag = await loop.run_in_executor(None, lambda: self.cdp.diagnose_sync())
                    self._log(diag.get("summary",""), "warn")
                except Exception:
                    pass
        except Exception as e:
            self._log(f"❌ Tab fetch failed: {e}", "error")


class AutoConnectPanel:

    @Slot(str, result=str)
    def auto_connect_scan(self, source: str):
        """Non-blocking auto-connect scan: rows + pool follow open tabs."""
        if not self.cdp or not self._page_pool:
            return json.dumps({"ok": False, "error": "CDP or pool not ready"})
        if self._auto_scan_running:
            return "pending"
        self._schedule_coro(self._do_auto_connect_scan(source or "auto"))
        return "pending"

    def _prune_auto_rows(self, plan) -> int:
        """Drop auto-linked rows whose tabs vanished; returns removed count."""
        if not plan.remove:
            return 0
        gone = set(plan.remove)
        before = len(self.state.urls)
        self.state.urls = [u for u in self.state.urls if u.id not in gone]
        return before - len(self.state.urls)

    def _apply_auto_plan(self, plan) -> bool:
        """Claim/add/prune URL rows from the plan; True when rows changed."""
        by_id = {u.id: u for u in self.state.urls}
        changed = False
        for row_id, tab_id in plan.claim:
            row = by_id.get(row_id)
            if row is not None and not row.tab_id:
                row.tab_id = tab_id
                changed = True
        added = _add_missing_rows(self.state.urls, plan.add)
        pruned = self._prune_auto_rows(plan)
        changed = bool(added) or changed or pruned > 0
        if changed:
            # system action, reproducible by re-scan: no undo spam
            self._save_arena()
            self._emit_arena_state()
        return changed

    def _report_auto_plan(self, plan, revived: int, stale: list, source: str):
        """Pool emit + summary; manual scans always answer, auto only on change."""
        if not self._plan_changed(plan, revived, stale):
            if source == "manual":
                self._log("🤖 Reparse: no changes — rows and pool already match open tabs", "info")
            return
        if self._plan_pool_dirty(plan, revived, stale):
            self._emit_pool_status()
        self._log(f"🤖 Auto-connect: +{len(plan.add)} rows, {len(plan.claim)} linked, "
                  f"{len(plan.connect)} joined, {revived} revived, {len(stale)} stale, "
                  f"{len(plan.remove)} removed", "info")

    @staticmethod
    def _plan_changed(plan, revived, stale) -> bool:
        """True when the reparse plan differs from current rows/pool state."""
        return bool(plan.add or plan.claim or plan.connect or revived or stale or plan.remove)

    @staticmethod
    def _plan_pool_dirty(plan, revived, stale) -> bool:
        """True when the plan touches pool membership (needs pool re-emit)."""
        return bool(plan.connect or revived or stale or plan.remove)

    async def _join_new_tabs(self, sockets) -> None:
        """Pool-join each connectable tab; skips empty sockets."""
        for ws in sockets or []:
            if ws:
                await self._do_connect_page_pool(ws)

    def _auto_prune_allowed(self, tabs) -> bool:
        """Prune dead rows only with a healthy tab list and no live run."""
        if getattr(self, "_run_state", "idle") != "idle":
            return False
        return any(getattr(t, "id", "") or getattr(t, "ws_url", "") for t in tabs or [])

    def _plan_auto_sync(self, tabs, pattern, rows):
        """Plan the scan; attach safe row pruning when allowed."""
        from app.services.auto_connect import live_tab_keys, plan_auto_connect, prunable_row_ids
        plan = plan_auto_connect(tabs, pattern, rows, self._pooled_ids())
        if self._auto_prune_allowed(tabs):
            plan.remove = prunable_row_ids(rows, live_tab_keys(tabs))
        return plan

    async def _do_auto_connect_scan(self, source: str = "auto"):
        """Fetch tabs, sync rows + pool + presence; skips when busy."""
        if self._auto_scan_running:
            return
        self._auto_scan_running = True
        try:
            from app.services.auto_connect import sync_pool_presence
            tabs = await self.cdp.fetch_tabs()
            pattern = self.config.get_state("url_pattern", "arena.ai")
            rows, removed = _dedupe_state_rows(self.state.urls)
            if removed:  # legacy broken state: N rows on one tab -> keep one (I-33)
                self._log(f"🤖 Auto-connect: removed {removed} extra row(s) — their tab already has a row", "warn")
            plan = self._plan_auto_sync(tabs, pattern, rows)
            self._apply_auto_plan(plan)
            await self._join_new_tabs(plan.connect)
            live = {(t.id or t.ws_url) for t in tabs or []} - {""}
            revived, stale = sync_pool_presence(self._page_pool, live)
            self._report_auto_plan(plan, revived, stale, source)
        except Exception as e:
            self._log(f"Auto-connect scan skipped: {e}", "warn")
        finally:
            self._auto_scan_running = False


class PopupPanel:

    def _popup_targets(self) -> list:
        """Titles of enabled rows with live pool tabs (deduped)."""
        titles, seen = [], set()
        try:
            pool = self._page_pool
            if not pool:
                return titles
            for u in self.state.urls:
                if not (u.enabled and u.tab_id) or u.tab_id in seen:
                    continue
                page = pool.get_page(u.tab_id)
                if page is None or not page.is_connected:
                    continue
                seen.add(u.tab_id)
                if page.title:
                    titles.append(page.title)
        except Exception:
            pass
        return titles

    @Slot(result=str)
    def popup_url_tabs(self):
        """Popup-on-top: raise OS windows of live URL tabs, tabs untouched."""
        if not self._page_pool:
            return json.dumps({"ok": False, "error": "pool not initialized"})
        self._schedule_coro(self._do_popup_url_tabs())
        return "pending"

    async def _do_popup_url_tabs(self):
        """Raise desktop windows of live URL tabs (no tab switching)."""
        from app.utils.win_popup import raise_window_titles
        targets = self._popup_targets()
        if not targets:
            self._log("⏫ Popup: no active URL tabs (need enabled + linked + connected)", "warn")
            return
        try:
            raised = raise_window_titles(targets)
        except Exception:
            raised = 0
        self._log(f"⏫ Popup: {raised}/{len(targets)} windows on top (tabs untouched)", "success")

    def _primary_ws(self) -> str:
        """Socket of the first live pool tab, else ''."""
        try:
            from app.services.auto_connect import pick_primary_ws
            pages = list(self._page_pool._pages.values()) if self._page_pool else []
            return pick_primary_ws(pages)
        except Exception:
            return ""

    async def _do_ensure_primary(self):
        """Passive primary retry: connect first live pool tab when down."""
        try:
            if not self.cdp or self.cdp.is_connected or self._ensure_running:
                return
            self._ensure_running = True
            try:
                ws = self._primary_ws()
                if ws and await self.cdp.connect(ws):
                    self._log("✅ Primary auto-connected — runs can start", "success")
                    self.connection_status.emit("connected")
            finally:
                self._ensure_running = False
        except Exception:
            pass

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
        self._schedule_coro(self._do_ensure_primary())
        return "pending"


class ConnectPanel:

    @Slot(str)
    def connect_tab(self, ws_url: str):
        if not self.cdp:
            self._log("CDP client not available", "error")
            return
        # Debounce: if same ws_url requested within 1.5s, skip duplicate
        try:
            import time
            now = time.time()
            if ws_url == self._last_connect_ws and (now - self._last_connect_ts) < 1.5:
                log.debug(f"connect_tab debounced duplicate {ws_url[:60]}")
                return
            if self._connect_in_progress and ws_url == self._last_connect_ws:
                log.debug(f"connect_tab already in progress for {ws_url[:60]}, skipping")
                return
            self._last_connect_ws = ws_url
            self._last_connect_ts = now
        except Exception:
            pass
        self._log(f"🔗 Connecting to {ws_url[:120]}… (port {self.cdp._port}, host {self.cdp._host})", "info")
        self._schedule_coro(self._do_connect_tab(ws_url))

    async def _do_connect_tab(self, ws_url: str):
        self._connect_in_progress = True
        try:
            if await self._connect_already_connected(ws_url):
                return
            ok = await self.cdp.connect(ws_url)
            if ok:
                self._log_connect_success(ws_url)
                # Also add to PagePool as steady page with dedicated client
                # (dedicated client per tab so 2+ tabs are truly independent)
                await self._pool_add_tab(ws_url)
            else:
                self._log_connect_failed(ws_url)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-1000:]
            self._log(f"❌ Connect exception for {ws_url[:80]}: {e} — {tb}", "error")
            self.connection_status.emit("error")
        finally:
            self._connect_in_progress = False

    async def _connect_already_connected(self, ws_url: str) -> bool:
        """True when already on this exact tab (reuse, skip reconnect race)."""
        try:
            if self.cdp and self.cdp.is_connected and self.cdp._current_tab_id:
                import re
                m = re.search(r'/devtools/page/([^/]+)$', ws_url)
                if m and m.group(1) == self.cdp._current_tab_id:
                    self._log(f"✅ Already connected to {ws_url[:80]} (reuse)", "success")
                    self.connection_status.emit("connected")
                    return True
        except Exception:
            pass
        return False

    def _log_connect_success(self, ws_url: str):
        self._log(f"✅ Connected to {ws_url[:80]} (tab {self.cdp._current_tab_id[:20]}…)", "success")
        self.connection_status.emit("connected")
        self._log(f"CDP session active on ws://{self.cdp._host}:{self.cdp._port}/devtools/page/{self.cdp._current_tab_id[:30]}", "info")

    def _log_connect_failed(self, ws_url: str):
        self._log(f"❌ Connect failed for {ws_url[:120]} — check Chrome still open on port {self.cdp._port}, try Diagnose", "error")
        self._log(f"💡 Tip: Ensure Chrome was started with --remote-debugging-port={self.cdp._port} --user-data-dir=... and that http://{self.cdp._host}:{self.cdp._port}/json/list shows JSON in browser", "warn")
        self.connection_status.emit("error")

    async def _pool_add_tab(self, ws_url: str):
        """Register the connected tab in the PagePool (warn-only on failure)."""
        try:
            if not self._page_pool:
                return
            info = await self._pool_tab_info(ws_url)
            existing_client, _ = self._page_pool.get_clients(info.tab_id)
            if existing_client and getattr(existing_client, 'is_connected', False):
                self._pool_reuse_client(info)  # update info only, keep client
            else:
                await self._pool_register_client(info)
            self._restore_page_state(info.tab_id)
        except Exception as e:
            import traceback as _tb
            self._log(f"Pool add primary failed: {e} {_tb.format_exc()[-500:]}", "warn")

    async def _pool_tab_info(self, ws_url: str):
        """Build PageInfo for the just-connected tab (live title/url fallback)."""
        import re as _re
        from app.browser.page_status import PageInfo
        m_id = _re.search(r'/devtools/page/([^/]+)$', ws_url)
        tab_id = m_id.group(1) if m_id else getattr(self.cdp, '_current_tab_id', '') or ws_url
        title = getattr(self.cdp, '_current_title', '') or ''
        url = getattr(self.cdp, '_current_url', '') or ''
        if not url or not title:
            live_title, live_url = await self._resolve_tab_info(tab_id, ws_url)
            title = title or live_title or tab_id
            url = url or live_url
        return PageInfo(tab_id=tab_id, ws_url=ws_url, title=title, url=url)

    def _pool_reuse_client(self, info):
        """Pool already has a dedicated client for this tab — refresh info only."""
        self._page_pool.add_page(info)
        self._emit_pool_status()
        self._log(f"📦 Pool: tab {info.tab_id[:12]} already has dedicated client steady (reuse)", "info")

    async def _pool_register_client(self, info):
        """Register a dedicated CDPClient for the tab (primary fallback)."""
        from app.browser.cdp_arena import CDPArenaController
        from app.browser.cdp_client import CDPClient
        dedicated = CDPClient(host=getattr(self.cdp, '_host', '127.0.0.1'),
                              port=getattr(self.cdp, '_port', 9222))
        ok2 = await dedicated.connect(info.ws_url)
        if ok2:
            self._pool_add_dedicated(info, dedicated)
        else:
            self._pool_add_primary(info)

    def _pool_add_dedicated(self, info, dedicated):
        """Steady page with its own websocket — parallel runs stay independent."""
        from app.browser.cdp_arena import CDPArenaController
        self._page_pool.add_page(info)
        ctrl2 = CDPArenaController(dedicated, log_callback=lambda m: self._log(m, "info"))
        self._page_pool.register_client(info.tab_id, dedicated, ctrl2)
        self._emit_pool_status()
        total, free = self._page_pool.get_counts()
        self._log(f"📦 Pool: added tab {info.tab_id[:12]} steady with dedicated client — total {total} pages {free} free", "success")
        if total >= 2:
            self._log(f"✅ {total} tabs in pool ready for parallel — when 2+ images selected, Run will dispatch to different webpages (steady/busy tracked, no double-send)", "success")

    def _pool_add_primary(self, info):
        """Dedicated client failed — register primary client as this tab's client."""
        from app.browser.cdp_arena import CDPArenaController
        self._page_pool.add_page(info)
        ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
        self._page_pool.register_client(info.tab_id, self.cdp, ctrl)
        self._emit_pool_status()
        total_f, _ = self._page_pool.get_counts() if self._page_pool else (0, 0)
        self._log(f"📦 Pool: added primary tab {info.tab_id[:12]} steady (dedicated failed, using primary) — total {total_f}", "warn")


class FindTabPanel:

    @Slot(str)
    def find_tab_by_url(self, query: str):
        """Non-blocking: schedule async matching in thread with debounce."""
        if not self.cdp:
            self._log("CDP not available", "error")
            return
        # Debounce: if same query within 1.0s, skip
        try:
            import time
            now = time.time()
            q = (query or "").strip()
            if q and q == self._last_find_query and (now - self._last_find_ts) < 1.0:
                log.debug(f"find_tab_by_url debounced duplicate {q[:60]}")
                return
            if self._find_in_progress:
                log.debug(f"find_tab_by_url already in progress, skipping {q[:60]}")
                return
            self._last_find_query = q
            self._last_find_ts = now
        except Exception:
            pass
        self._schedule_coro(self._do_find_tab(query))

    async def _do_find_tab(self, query: str):
        self._find_in_progress = True
        try:
            query = (query or "").strip()
            if not query:
                self._log("⚠ URL field empty", "warn")
                self.tab_match_result.emit(query, "[]")
                return
            try:
                tabs = await self.cdp.fetch_tabs()
                if not tabs:
                    await self._find_no_tabs_hint()
                    self.tab_match_result.emit(query, "[]")
                    return
                self._find_emit_matches(query, tabs)
            except Exception as e:
                self._log(f"❌ Tab matching failed: {e}", "error")
                self.tab_match_result.emit(query, "[]")
        finally:
            self._find_in_progress = False

    async def _find_no_tabs_hint(self):
        """No tabs visible: run sync diagnose and log the Chrome start hint."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            diag = await loop.run_in_executor(None, lambda: self.cdp.diagnose_sync())
            self._log(diag.get("summary", "⚠ No Chrome tabs found"), "warn")
            self._log(f"💡 Fix: 1) Close ALL Chrome windows. 2) Run: \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --remote-debugging-port={self.cdp._port} --user-data-dir=\"C:\\arena-images-chrome\" 3) Open https://arena.ai in that NEW Chrome window. 4) Click Diagnose. 5) Open http://{self.cdp._host}:{self.cdp._port}/json/list — you should see JSON.", "warn")
        except Exception:
            self._log(f"⚠ No Chrome tabs found — start Chrome with --remote-debugging-port={self.cdp._port} --user-data-dir=\"C:\\arena-images-chrome\"", "warn")

    def _find_emit_matches(self, query: str, tabs):
        """Emit best matches for query over fetched tabs."""
        tab_dicts = [{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs]
        matches = best_matches(query, tab_dicts)
        if not matches:
            self._log(f"❌ No tab matches “{query}”. Available: " + "; ".join(f"{t.title} — {t.url}" for t in tabs[:5]), "error")
            self.tab_match_result.emit(query, "[]")
            return
        for m in matches[:3]:
            self._log(f"  · match ({m['kind']}): {m['title']} — {m['url']}", "success")
        self.tab_match_result.emit(query, json.dumps(matches, ensure_ascii=False))


class CdpTestPanel:

    @Slot(str, result=str)
    def cdp_attach_image_test(self, image_id: str):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        img = self._test_image_for(image_id)
        if not img:
            return json.dumps({"ok": False, "error": "No image found, select one in queue"})
        self._log(f"🧪 Testing attach for {img.absolute_path}", "info")
        self._schedule_coro(self._do_cdp_attach_test(img.absolute_path))
        return json.dumps({"ok": True, "path": img.absolute_path})

    def _test_image_for(self, image_id: str):
        """Image for a CDP test: by id, else first selected."""
        for im in self.state.images:
            if im.id == image_id or (not image_id and im.selected):
                return im
        sel = [i for i in self.state.images if i.selected]
        return sel[0] if sel else None

    async def _do_cdp_attach_test(self, image_path: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            ok, reason = await ctrl.attach_image(image_path)
            if ok:
                self._log(f"✅ Attach test success: {reason}", "success")
            else:
                self._log(f"❌ Attach test failed: {reason}", "error")
        except Exception as e:
            self._log(f"Attach test exception: {e}", "error")

    @Slot(str, result=str)
    def cdp_insert_prompt_test(self, prompt_text: str):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        txt = prompt_text or self.state.prompt.get("user_prompt","") or "Test prompt [JOB-ID: test123]"
        self._log(f"🧪 Testing prompt insert: {txt[:80]}...", "info")
        self._schedule_coro(self._do_cdp_prompt_test(txt))
        return json.dumps({"ok": True})

    async def _do_cdp_prompt_test(self, prompt_text: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            ok, reason = await ctrl.insert_prompt(prompt_text)
            if ok:
                self._log(f"✅ Prompt insert success: {reason}", "success")
                verified, vreason = await ctrl.verify_prompt(prompt_text)
                self._log(f"Verify prompt: {verified} {vreason}", "info" if verified else "warn")
            else:
                self._log(f"❌ Prompt insert failed: {reason}", "error")
        except Exception as e:
            self._log(f"Prompt test exception: {e}", "error")

    @Slot(result=str)
    def cdp_test_full_flow(self):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        sel = [i for i in self.state.images if i.selected]
        if not sel:
            return json.dumps({"ok": False, "error": "No selected image"})
        prompt = self.state.prompt.get("user_prompt","")
        if not prompt:
            return json.dumps({"ok": False, "error": "Empty prompt"})
        self._log(f"🧪 Testing full flow: attach + prompt + submit (without waiting)", "info")
        self._schedule_coro(self._do_cdp_full_flow_test(sel[0].absolute_path, prompt))
        return json.dumps({"ok": True})

    async def _do_cdp_full_flow_test(self, image_path: str, prompt_template: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            from app.utils.correlation import generate_correlation_id, build_final_prompt
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            baseline = await ctrl.capture_baseline()
            self._log(f"Baseline {baseline.get('output_count')} outputs", "info")
            ok, reason = await ctrl.attach_image(image_path)
            self._log(f"Attach: {ok} {reason}", "success" if ok else "error")
            if not ok:
                return
            cid = generate_correlation_id()
            final = build_final_prompt(cid, prompt_template)
            ok, reason = await ctrl.insert_prompt(final)
            self._log(f"Insert prompt [{cid}]: {ok} {reason}", "success" if ok else "error")
            if not ok:
                return
            ok, reason = await ctrl.submit()
            self._log(f"Submit: {ok} {reason}", "success" if ok else "error")
        except Exception as e:
            self._log(f"Full flow test exception: {e}", "error")
