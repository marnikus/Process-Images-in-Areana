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
from functools import partial

from app.services.auto_connect import pick_primary_ws
from app.services.live.reconcile import LiveDeps, reconcile_once, start_reconciler
from app.services.run_state import (
    pooled_ids,
    resolve_tab_info,
    restore_page_state,
    schedule_coro,
    tab_label_of,
)
from app.ui.panels.page_pool import connect_pool_client, do_connect_page_pool, leave_pool
from app.ui.panels.url_queue import commit_urls_system
from app.ui.qt_compat import Slot
from app.utils.win_popup import raise_window_titles

log = logging.getLogger("arena")


def active_browser(bridge):
    """The registry row of the selected browser (None when the registry says no)."""
    from app.browser import browsers
    try:
        stored = bridge.config.get_state("active_browser", "")
        return browsers.profile_of(stored) or browsers.default_profile()
    except Exception:
        return None


def uses_rdp(bridge) -> bool:
    """Is the panel pointed at a Firefox DevTools socket (not a CDP endpoint)?"""
    from app.browser import browsers
    profile = active_browser(bridge)
    return bool(profile and profile.protocol == browsers.PROTOCOL_RDP)


def _base_port(value, default: int = 9222) -> int:
    """A usable shared base port from stored state (bad or empty values fall back)."""
    try:
        base = int(value)
    except Exception:
        return default
    return base if 1 <= base <= 65535 else default


def scan_settings(bridge) -> tuple:
    """What one pass scans: (browser rows, shared base port, host) from the settings window.

    Round 9: the pass follows the *settings*, not whichever browser happens to be
    selected — "if it starts from 9223 then app should parse all page on ws: 9223,
    ws: 9224 and ws: 9225 … all that defined in win settings".
    """
    try:
        config = bridge.config
        rows = config.get_state("cdp_browsers", {}) or {}
        host = config.get_state("cdp_host", "127.0.0.1") or "127.0.0.1"
        return rows, _base_port(config.get_state("cdp_port", 9222)), host
    except Exception:
        cdp = getattr(bridge, "cdp", None)
        return {}, 9222, getattr(cdp, "_host", "127.0.0.1") or "127.0.0.1"


def report_scan_notes(bridge, notes) -> None:
    """Log each browser that did not answer — once per reason, never once per pass.

    A note is only news when it changes: the same missing browser on the same endpoint
    must not reprint its line every pass (the owner's log was a loop). The reason is
    dropped as soon as the browser answers again, so a later failure prints again.
    """
    seen = getattr(bridge, "_scan_note_reasons", None)
    if seen is None:                       # one dict per bridge — recording must alias it
        seen = {}
        bridge._scan_note_reasons = seen
    current = {note.browser: note.reason for note in notes}
    for note in notes:
        if seen.get(note.browser) != note.reason:
            bridge._log(f"❌ {note.browser}: {note.reason}", "warn")
    seen.clear()
    seen.update(current)


def row_key(row) -> str:
    """A tab row's id, whichever channel's shape it is (`id` for both today)."""
    return getattr(row, "id", "") or getattr(row, "tab_id", "") or ""


def merge_rows(scanned, extra) -> list:
    """Scanned rows first, then the client's own tabs the scan did not already name."""
    merged, seen = list(scanned), {row_key(r) for r in scanned if row_key(r)}
    for row in extra:
        key = row_key(row)
        if key and key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


async def active_client_rows(bridge) -> list:
    """The active client's own tab list — the last resort when the scan listed nothing.

    A client attached to a tab on an endpoint the settings do not describe still knows
    that tab exists; before reporting an empty list, ask it. (Every channel routes here:
    the client lists over its own protocol, never HTTP on a DevTools socket.)
    """
    fetch = getattr(getattr(bridge, "cdp", None), "fetch_tabs", None)
    if fetch is None:
        return []
    try:
        return list(await fetch() or [])
    except Exception:
        return []


def scan_targets(bridge) -> list:
    """Every enabled browser's tabs in one pass, each from its own endpoint/channel."""
    from app.browser import endpoints
    rows, base, host = scan_settings(bridge)
    return endpoints.enabled_targets(rows, base, host, 3.0)


async def live_tab_rows(bridge):
    """Parse every enabled browser in one pass — Chrome's sockets, Firefox's `rdp://` rows.

    One seam for the whole app: the reconciler, the pool panel and this panel's own
    listing all read through here, so a browser switched off is never scanned, a browser
    that is down never hides a live one, and no HTTP request is ever sent to a DevTools
    socket (Round 9: that was the owner's `URLError …/json/list: Not Found` loop).
    """
    loop = asyncio.get_event_loop()
    try:
        rows, notes = await loop.run_in_executor(None, lambda: scan_targets(bridge))
    except Exception as e:
        bridge._scan_failed, bridge._scan_missing = str(e), {}
        bridge._log(f"❌ Scan failed: {e}", "error")
        return []
    bridge._scan_failed = ""
    report_scan_notes(bridge, notes)
    bridge._scan_missing = {n.browser: n.reason for n in notes}   # one dict, aliased on purpose
    if rows:
        return rows
    return merge_rows(rows, await active_client_rows(bridge))


async def reconcile_tabs(bridge):
    """`live_tab_rows` for the reconciler — a pass no browser answered is a failure (D-1).

    Returning `[]` there would look exactly like "every tab was closed": the rows would
    advance their miss counts and, after the threshold, be removed for tabs that are
    still open. The reconciler already knows how to wait (`_fetch` → "Reconcile
    skipped"), so an unusable pass says so instead of pretending to be empty.
    """
    from app.browser.endpoints import ScanUnavailable
    rows = await live_tab_rows(bridge)
    missing = getattr(bridge, "_scan_missing", None) or {}
    reason = getattr(bridge, "_scan_failed", "") or ("; ".join(missing.values()) if missing else "")
    if not rows and reason:
        raise ScanUnavailable(reason[:300])
    return rows


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
    """Success logs + status for a fresh connection (one line per channel, D-8)."""
    from app.browser import attached
    tab_id = getattr(bridge.cdp, "_current_tab_id", "") or ""
    bridge._log(f"✅ Connected to {ws_url[:80]} (tab {tab_id[:20]}…)", "success")
    bridge.connection_status.emit("connected")
    if attached.is_remote(attached.parse_handle(ws_url)):
        bridge._log(f"🦊 Attached to {tab_id} over the browser's DevTools socket — one socket for "
                    f"the whole browser, actions run as JS in this tab, detach leaves it running", "info")
        return
    bridge._log(f"CDP session active on ws://{bridge.cdp._host}:{bridge.cdp._port}/devtools/page/{tab_id[:30]}", "info")


def pool_page_for(bridge, identity):
    """The pool row for a connect-path join — named with the tab's own browser (D-5).

    The connect path joins tabs from any enabled browser, so the row cannot be built from
    the pool's active endpoint: `pool_page_info` reads the handle's owner from the settings
    rows, which is what labels a Firefox row `firefox` instead of leaving it blank.
    """
    from app.browser import attached
    from app.ui.panels.page_pool import pool_page_info
    tab_id, ws_url, title, url = identity
    pool = getattr(bridge, "_page_pool", None)
    host = getattr(pool, "_host", "127.0.0.1") or "127.0.0.1"
    port = getattr(pool, "_port", 9222) or 9222
    return pool_page_info(bridge, attached.parse_handle(ws_url, host, port), title, url)


def reuse_pool_page(bridge, identity) -> None:
    """Pool already holds a live dedicated client: refresh info only."""
    tab_id, _ws_url, _title, _url = identity
    bridge._page_pool.add_page(pool_page_for(bridge, identity))
    bridge._emit_pool_status()
    label = tab_label_of(getattr(bridge, "_page_pool", None), tab_id)
    bridge._log(f"📦 Pool: tab {label} already has dedicated client steady (reuse)", "info")


async def add_dedicated_pool_page(bridge, identity) -> None:
    """Pool-join with an independent per-tab client (parallel-safe)."""
    from app.browser.cdp_arena import CDPArenaController
    tab_id, ws_url, _title, _url = identity
    dedicated = await connect_pool_client(bridge, ws_url)   # endpoint + channel from the handle
    if dedicated is None:
        add_fallback_pool_page(bridge, identity)
        return
    bridge._page_pool.add_page(pool_page_for(bridge, identity))
    ctrl2 = CDPArenaController(dedicated, log_callback=lambda m: bridge._log(m, "info"))
    bridge._page_pool.register_client(tab_id, dedicated, ctrl2)
    bridge._emit_pool_status()
    total, free = bridge._page_pool.get_counts()
    label = tab_label_of(getattr(bridge, "_page_pool", None), tab_id)
    bridge._log(f"📦 Pool: added tab {label} steady with dedicated client — total {total} pages {free} free", "success")
    if total >= 2:
        bridge._log(f"✅ {total} tabs in pool ready for parallel — when 2+ images selected, Run will dispatch to different webpages (steady/busy tracked, no double-send)", "success")


def add_fallback_pool_page(bridge, identity) -> None:
    """Pool-join reusing the primary client (dedicated connect failed) — CDP tabs only.

    A tab on another browser's endpoint must never fall back to the primary client: that
    would send its actions to a different browser, silently. A remote handle whose own
    attach failed stays out of the pool and says why (D-8).
    """
    from app.browser import attached
    from app.browser.cdp_arena import CDPArenaController
    tab_id, ws_url, _title, _url = identity
    handle = attached.parse_handle(ws_url, getattr(bridge.cdp, "_host", "127.0.0.1"),
                                   getattr(bridge.cdp, "_port", 9222))
    if attached.is_remote(handle):
        bridge._log(f"⚠ Pool: {tab_id} stayed out — its own {handle.channel.upper()} attach failed; "
                    f"the primary client cannot drive a tab on {handle.host}:{handle.port}", "warn")
        return
    bridge._page_pool.add_page(pool_page_for(bridge, identity))
    ctrl = CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
    bridge._page_pool.register_client(tab_id, bridge.cdp, ctrl)
    bridge._emit_pool_status()
    total_f, _ = bridge._page_pool.get_counts() if bridge._page_pool else (0, 0)
    label = tab_label_of(getattr(bridge, "_page_pool", None), tab_id)
    bridge._log(f"📦 Pool: added primary tab {label} steady (dedicated failed, using primary) — total {total_f}", "warn")


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
            bridge._log(f"❌ Connect failed for {ws_url[:120]}: {connect_reason(bridge, ws_url)}", "error")
            bridge.connection_status.emit("error")
    except Exception as e:
        import traceback
        bridge._log(f"❌ Connect exception for {ws_url[:80]}: {e} — {traceback.format_exc()[-1000:]}", "error")
        bridge.connection_status.emit("error")
    finally:
        bridge._connect_in_progress = False


def connect_reason(bridge, ws_url: str) -> str:
    """Why that attach failed, in the words of the endpoint that was asked (D-7).

    Round 8 printed Chrome's tip for every channel — including `--remote-debugging-port`
    and a `/json/list` link for a Firefox DevTools socket, which is exactly the loop the
    owner pasted. The reason is now classified per endpoint and per channel.
    """
    from app.browser import attached, browsers
    handle = attached.parse_handle(ws_url, getattr(bridge.cdp, "_host", "127.0.0.1"),
                                   getattr(bridge.cdp, "_port", 9222))
    profile = (browsers.profile_of(handle.browser) or browsers.profile_for_protocol(handle.channel)
               or browsers.default_profile())
    return (getattr(bridge.cdp, "last_error", "") or "").strip() or attached.explain_failure(
        handle, profile, 1.0)


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


def firefox_fix_tip(bridge) -> str:
    """What to do when a Firefox DevTools socket answers with no tabs."""
    return (f"💡 Fix: 1) Start Firefox with --start-debugger-server {bridge.cdp._port} "
            '(profile prefs: devtools.debugger.remote-enabled=true, '
            'devtools.debugger.prompt-connection=false). 2) Open https://arena.ai in that '
            "Firefox. 3) Click Refresh or Diagnose — attach/detach never restarts it.")


async def report_no_tabs(bridge, query: str) -> None:
    """Diagnose an empty tab list (executor diag + fix tip), answer []."""
    if uses_rdp(bridge):
        bridge._log(firefox_fix_tip(bridge), "warn")
        bridge.tab_match_result.emit(query, "[]")
        return
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
    """Fetch tabs (whichever protocol the active browser speaks); route the report."""
    tabs = await live_tab_rows(bridge)
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
    """Fetch live tabs (CDP or Firefox RDP); an empty list also drops a diagnose."""
    try:
        tabs = await live_tab_rows(bridge)
        payload = json.dumps([{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs], ensure_ascii=False)
        bridge.tabs_received.emit(payload)
        if not tabs and not (getattr(bridge, "_scan_missing", None) or {}):
            try:                     # every endpoint answered — ask the active one for details
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


async def do_diagnose_rdp(bridge) -> None:
    """Executor-diagnose the Firefox DevTools socket: greeting, prefix, tabs."""
    from app.browser import rdp
    loop = asyncio.get_event_loop()
    info, err = await loop.run_in_executor(None, lambda: rdp.session_info(
        rdp.Endpoint(bridge.cdp._host, bridge.cdp._port), 3.0))
    if err:
        bridge._log(f"❌ {err}", "warn")
        bridge._log(firefox_fix_tip(bridge), "warn")
        return
    bridge._log(f"✅ Firefox DevTools (RDP) socket on {info['host']}:{info['port']} — "
                f"{info['application']} session, {info['tabs']} tab(s), actor prefix "
                f"{info['prefix']}* (actors are re-resolved on every attach)", "success")
    rows = await live_tab_rows(bridge)
    if rows:
        payload = json.dumps([{"id": t.id, "title": t.title, "url": t.url,
                               "ws_url": t.ws_url} for t in rows], ensure_ascii=False)
        bridge.tabs_received.emit(payload)


async def do_diagnose_chrome(bridge) -> None:
    """Executor-diagnose the active browser: CDP checks, or the DevTools socket."""
    if uses_rdp(bridge):
        await do_diagnose_rdp(bridge)
        return
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


def live_deps(bridge) -> LiveDeps:
    """The reconciler's callables, wired in ui land (the service never imports ui/browser).

    `fetch_tabs` is the panel's own one-pass listing — every enabled browser at its own
    endpoint (`chrome` 9223, `firefox` 9224, `edge` 9225 …), each row tagged with the
    browser and channel it came from. Round 9: the reconciler used to see only the active
    browser's endpoint, which is why a Firefox tab could never be planned, joined or
    labelled (D-1).
    """
    async def fetch_tabs():
        return await reconcile_tabs(bridge)

    async def join_tab(ws: str):
        await do_connect_page_pool(bridge, ws)

    def leave_tab(tab_id: str) -> bool:
        left = leave_pool(bridge, tab_id)  # badge cleared, page removed (the one leave mechanic)
        bridge._emit_pool_status()
        return left

    return LiveDeps(fetch_tabs=fetch_tabs, join_tab=join_tab, leave_tab=leave_tab,
                    commit=partial(commit_urls_system, bridge), log=bridge._log)


def start_url_reconciler(bridge) -> bool:
    """Boot-time start of the Python-owned URL loop (idempotent; False when already running)."""
    return start_reconciler(bridge, live_deps(bridge))


async def auto_scan_pass(bridge, source: str) -> None:
    """One scan (delegation: the body lives in `live.reconcile.reconcile_once`)."""
    await reconcile_once(bridge, live_deps(bridge), source)


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
        self._log(f"🩺 Diagnosing {active_browser(self).label if active_browser(self) else 'browser'} "
                  f"on {self.cdp._host}:{self.cdp._port}… (non-blocking)", "info")
        schedule_coro(self, do_diagnose_chrome(self))
        return "pending"

    @Slot(str, result=str)
    def auto_connect_scan(self, source: str):
        """Non-blocking auto-connect scan: rows + pool follow open tabs."""
        if not self.cdp or not self._page_pool:
            return json.dumps({"ok": False, "error": "CDP or pool not ready"})
        if self._auto_scan_running:
            return "pending"  # a pass is in flight; the reconciler owns the flag
        schedule_coro(self, reconcile_once(self, live_deps(self), source or "auto"))
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
        from app.browser import attached
        if not self.cdp:
            self._log("CDP client not available", "error")
            return
        handle = attached.parse_handle(ws_url, getattr(self.cdp, "_host", "127.0.0.1"),
                                       getattr(self.cdp, "_port", 9222))
        refusal = attached.refusal(handle, "connect")
        if refusal:
            self._log(f"❌ {refusal}", "warn")
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
