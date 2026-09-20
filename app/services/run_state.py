# ideal-size: ~420 lines reason=single scheduling seam owns bg-loop/schedule plus tab/pool/restore glue sharing bridge duck-type helpers; splitting would scatter one run-support surface used jointly by orchestrator and panels (RULE 18.2)
"""Run-state seam: bg loop, scheduling, pool-page ensure/restore (Area A3).

Single source for the async/scheduling glue shared by the batch
orchestrator and the UI panels. Operates on the bridge duck-type
(attrs only, no Qt import) so services stay Qt-free (RULE 16 seam).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.browser.page_status import PageInfo
from app.persistence.cooldown_store import (
    consume_entry_for,
    describe_cooldown_file,
    load_entries,
    load_stats,
    normalize_url,
    save_entries,
    save_pool_snapshot,
)
from app.services.cooldown_service import (
    ensure_pool_page as _cds_ensure_page,
)
from app.services.cooldown_service import (
    restore_cooldown_entry,
    restore_page_stats,
)

log = logging.getLogger("arena")


@dataclass
class RestoreNote:
    """Parameter object for cooldown-restore logging (RULE 19)."""

    tab_id: str
    page_url: str
    entries: Dict[str, Any]
    report: Dict[str, Any]


# ---- background loop ----

def _bg_primitives(bridge) -> None:
    """Recreate bg lock/event when missing (migration-safe)."""
    if not isinstance(getattr(bridge, "_bg_lock", None), type(threading.Lock())):
        bridge._bg_lock = threading.Lock()
    if not isinstance(getattr(bridge, "_bg_ready", None), type(threading.Event())):
        bridge._bg_ready = threading.Event()


def _running_loop(bridge):
    """The bg loop when alive, else None."""
    loop = getattr(bridge, "_bg_loop", None)
    if loop is not None and loop.is_running():
        return loop
    return None


def _run_loop_forever(bridge) -> None:
    """Bg-thread target: own event loop, run forever."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bridge._bg_loop = loop
        bridge._bg_ready.set()
        loop.run_forever()
    except Exception as e:
        log.warning(f"bg loop crashed: {e}")
        try:
            bridge._bg_ready.set()
        except Exception:
            pass


def _spawn_bg_loop(bridge) -> None:
    """Start the bg thread once (double-checked under lock)."""
    with bridge._bg_lock:
        if _running_loop(bridge) is not None:
            return
        try:
            bridge._bg_ready.clear()
        except Exception:
            bridge._bg_ready = threading.Event()
        thread = threading.Thread(target=_run_loop_forever, args=(bridge,),
                                  daemon=True, name="arena-bg-loop")
        thread.start()
        bridge._bg_thread = thread


def ensure_bg_loop(bridge):
    """Persistent bg loop for CDP (keeps websockets alive)."""
    try:
        _bg_primitives(bridge)
        loop = _running_loop(bridge)
        if loop is not None:
            return loop
        _spawn_bg_loop(bridge)
        try:
            bridge._bg_ready.wait(timeout=5)
        except Exception:
            pass
        return getattr(bridge, "_bg_loop", None)
    except Exception as e:
        log.warning(f"ensure_bg_loop failed: {e}")
        return None


# ---- scheduling ----

def batch_active(bridge) -> bool:
    """True while a batch future is alive — running, paused, stopping or still unwinding (I-45)."""
    fut = getattr(bridge, "_batch_future", None)
    return fut is not None and not fut.done()


def _clear_batch_future(bridge, fut) -> None:
    """Forget the batch future once done."""
    try:
        if bridge._batch_future is fut:
            bridge._batch_future = None
    except Exception:
        pass


def _failure_note(fut) -> Optional[BaseException]:
    """Done-future error, or None when clean/cancelled."""
    try:
        err = fut.exception()
    except Exception as e:
        return None if "Cancel" in type(e).__name__ else e
    if err is None:
        return None
    return None if "Cancel" in type(err).__name__ else err


def _on_coro_done(bridge, fut) -> None:
    """Log background failures; always release the batch future."""
    err = _failure_note(fut)
    if err is not None:
        log.warning(f"coro thread failed: {err}")
        try:
            bridge._log(f"Async task failed: {err}", "error")
        except Exception:
            pass
    _clear_batch_future(bridge, fut)


def _submit_tracked(bridge, loop, coro):
    """Submit + done-callback on the live bg loop (the batch future is tracked by `schedule_batch`)."""
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    future.add_done_callback(lambda fut: _on_coro_done(bridge, fut))
    return future


def _run_detached(bridge, coro):
    """Fallback: short-lived thread when no bg loop exists."""
    def _run():
        try:
            asyncio.run(coro)
        except Exception as e:
            log.warning(f"coro thread fallback failed: {e}")
            try:
                bridge._log(f"Async task failed: {e}", "error")
            except Exception:
                pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return None


@dataclass
class JobAction:
    """Runner→UI block-status event (F8: replaces the 5-arg seam)."""
    job_id: str
    block: Any
    status: str
    message: str = ""
    rect: Optional[dict] = None


def schedule_coro(bridge, coro):
    """Non-blocking schedule on the bg loop (None when detached)."""
    try:
        loop = ensure_bg_loop(bridge)
        if loop is not None and loop.is_running():
            return _submit_tracked(bridge, loop, coro)
        return _run_detached(bridge, coro)
    except Exception as e:
        log.warning(f"schedule_coro failed: {e}")
        try:
            coro.close()
        except Exception:
            pass
        return None


def schedule_batch(bridge, coro):
    """Schedule THE run coroutine and always track it as the batch future (S4: no name sniffing)."""
    future = schedule_coro(bridge, coro)
    if future is not None:
        bridge._batch_future = future
    return future


# ---- tab identity ----

def _cdp_attrs(bridge) -> Tuple[str, str]:
    """Best-known (title, url) from cdp attrs."""
    cdp = getattr(bridge, "cdp", None)
    return _cdp_attr(cdp, "_current_title"), _cdp_attr(cdp, "_current_url")


async def _fetch_tabs_safe(bridge) -> List[Any]:
    """Live tabs, [] on any failure."""
    try:
        return await bridge.cdp.fetch_tabs() or []
    except Exception:
        return []


def _tab_attr(tab: Any, name: str) -> str:
    """Tab attribute as text (missing-safe)."""
    try:
        return getattr(tab, name, "") or ""
    except Exception:
        return ""


def _match_tab(tabs: List[Any], tab_id: str, ws_url: str) -> Optional[Tuple[str, str]]:
    """First tab matching id or ws url (guard clauses, no nesting)."""
    for tab in tabs or []:
        if tab_id and _tab_attr(tab, "id") == tab_id:
            return _tab_attr(tab, "title"), _tab_attr(tab, "url")
        if ws_url and _tab_attr(tab, "ws_url") == ws_url:
            return _tab_attr(tab, "title"), _tab_attr(tab, "url")
    return None


async def resolve_tab_info(bridge, tab_id: str, ws_url: str) -> Tuple[str, str]:
    """Best-known (title, url): live tabs first, cdp attrs then."""
    title, url = _cdp_attrs(bridge)
    hit = _match_tab(await _fetch_tabs_safe(bridge), tab_id, ws_url)
    if hit is None:
        return title, url
    return hit[0] or title, hit[1] or url


# ---- pool-page ensure/restore ----

def _pool_needs_page(bridge, tab_id: str) -> bool:
    """True when the pool lacks this tab or its identity."""
    pool = getattr(bridge, "_page_pool", None)
    if not pool or not tab_id:
        return False
    page = pool.get_page(tab_id)
    if page is None:
        return True
    return not (getattr(page, "url", "") and getattr(page, "title", ""))


def _cdp_attr(cdp, name: str) -> str:
    """One cached CDP field, normalized to str."""
    return getattr(cdp, name, "") or ""


async def _page_identity(bridge, tab_id: str) -> Tuple[str, str, str]:
    """(ws, title, url) for registering this tab."""
    cdp = getattr(bridge, "cdp", None)
    ws = _cdp_attr(cdp, "_current_ws_url")
    title = _cdp_attr(cdp, "_current_title")
    url = _cdp_attr(cdp, "_current_url")
    if not url or not title:
        live_title, live_url = await resolve_tab_info(bridge, tab_id, ws)
        title = title or live_title or tab_id
        url = url or live_url
    return ws, title, url


async def ensure_pool_page(bridge, tab_id: str) -> None:
    """Register the run tab for cooldown tracking (batch self-sufficiency)."""
    if not _pool_needs_page(bridge, tab_id):
        return
    try:
        ws, title, url = await _page_identity(bridge, tab_id)
        _cds_ensure_page(bridge._page_pool,
                         PageInfo(tab_id=tab_id, ws_url=ws, title=title, url=url))
        restore_page_state(bridge, tab_id)
        bridge._emit_pool_status()
    except Exception as e:
        bridge._log(f"Pool ensure skipped: {e}", "warn")


def cooldowns_path(bridge) -> str:
    """config/cooldowns.json next to the other stores."""
    try:
        base = getattr(bridge.config, "dir", None)
        if base:
            return str(Path(base) / "cooldowns.json")
    except Exception:
        pass
    return "config/cooldowns.json"


def persist_cooldowns(bridge) -> None:
    """Autosave wall-clock timers + job counters across restarts."""
    try:
        if not getattr(bridge, "_page_pool", None):
            return
        save_pool_snapshot(cooldowns_path(bridge), bridge._page_pool)
        if not getattr(bridge, "_persist_ok", True):
            bridge._persist_ok = True
            bridge._log("✅ Cooldown autosave recovered", "success")
    except Exception as e:
        if getattr(bridge, "_persist_ok", True):
            bridge._persist_ok = False
            bridge._log(f"⚠ Cooldown autosave failing ({e}) — timers will NOT survive restart", "warn")


def pooled_ids(pool) -> set:
    """Ids currently in the pool; empty when unavailable."""
    try:
        return set(pool._pages.keys())
    except Exception:
        return set()


def _restore_job_counter(bridge, tab_id: str, page_url: str) -> None:
    """Re-apply one tab's saved job counter (never moves backwards)."""
    try:
        stats = load_stats(cooldowns_path(bridge))
        restore_page_stats(bridge._page_pool, tab_id, normalize_url(page_url), stats)
    except Exception:
        pass


def _log_file_note(bridge, report: Dict[str, Any]) -> None:
    """One file-level note, once per process (nothing live to resume)."""
    if getattr(bridge, "_restore_note_done", False):
        return
    bridge._restore_note_done = True
    if not report.get("exists"):
        bridge._log("⏳ No saved timers file yet — nothing to resume", "info")
    elif report.get("dropped"):
        bridge._log(f"⏳ Saved timer(s) already expired while app was closed ({len(report['dropped'])} dropped) — tab starts ready", "info")
    else:
        bridge._log("⏳ Saved timers file is empty — nothing to resume", "info")


def _log_tab_miss(bridge, note: RestoreNote) -> None:
    """Loud per-tab note: live timers exist, but for other tabs."""
    want = f"{note.tab_id[:12]} / {note.page_url[:60]}"
    have = ", ".join(f"{k[:8]}:{(v.get('url', '') if isinstance(v, dict) else '')[:40]}"
                     for k, v in list(note.entries.items())[:5])
    live = note.report.get("live", 0)
    bridge._log(f"⚠ Cooldown restore missed for {want} — {live} live saved timer(s) for other tabs ({have}); tab ids/URLs changed since save?", "warn")


def _announce_restore(bridge, tab_id: str) -> None:
    """Announce a consumed entry and emit the pool snapshot."""
    page = bridge._page_pool.get_page(tab_id)
    left = page.remaining_seconds() if page else 0
    bridge._log(f"⏳ Restored cooldown for {tab_id[:12]}: {left // 60:02d}:{left % 60:02d} left (timer kept running while app was closed)", "info")
    bridge._emit_pool_status()


def _page_url_of(pool, tab_id: str) -> str:
    """Live URL of a pooled page (missing-safe)."""
    page = pool.get_page(tab_id)
    return getattr(page, "url", "") if page else ""


def _log_restore_miss(bridge, note: RestoreNote) -> None:
    """File-level note when nothing live, else loud per-tab miss."""
    if note.report.get("live", 0) == 0:
        _log_file_note(bridge, note.report)
    else:
        _log_tab_miss(bridge, note)


def _saved_entry_or_note(bridge, tab_id: str):
    """Consume this tab's saved entry; log file/tab miss when absent."""
    pool = getattr(bridge, "_page_pool", None)
    page_url = _page_url_of(pool, tab_id) if pool else ""
    path = cooldowns_path(bridge)
    entries = load_entries(path)
    _key, entry = consume_entry_for(entries, tab_id, page_url, pooled_ids(pool))
    if entry:
        return entries, entry
    note = RestoreNote(tab_id=tab_id, page_url=page_url,
                       entries=entries, report=describe_cooldown_file(path))
    _log_restore_miss(bridge, note)
    return entries, None


def restore_page_state(bridge, tab_id: str) -> None:
    """Re-apply persisted wall-clock pause + job counter after restart."""
    try:
        pool = getattr(bridge, "_page_pool", None)
        if not pool or not tab_id:
            return
        path = cooldowns_path(bridge)
        page_url = _page_url_of(pool, tab_id)
        _restore_job_counter(bridge, tab_id, page_url)
        entries, entry = _saved_entry_or_note(bridge, tab_id)
        if not entry:
            return
        if not restore_cooldown_entry(pool, tab_id, entry):
            return
        save_entries(path, entries)
        _announce_restore(bridge, tab_id)
    except Exception as e:
        bridge._log(f"Cooldown restore skipped: {e}", "warn")
