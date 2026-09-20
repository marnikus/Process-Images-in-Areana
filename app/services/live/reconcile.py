# ideal-size: ~215 lines reason=S6 — URL reconcile cadence owned by Python; loop reads interval every pass, rows follow Chrome, joins via S1, commits via S4 funnel (RULE 18.2)
"""live/reconcile (S6) — Python-owned URL loop + one-pass diff (I-42)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass

from app.services.auto_connect import enabled_tab_ids, live_tab_keys, plan_auto_connect
from app.services.live.bus import live_bus
from app.services.live.debug_view import clamp_interval_ms, interval_ms
from app.services.live.feed import clear_row_assignments
from app.services.live.url_policy import (
    RemovalSpec,
    add_rows,
    advance_misses,
    dedupe_rows,
    remember,
    removable_rows,
    removal_lines,
)
from app.services.run_state import pooled_ids, schedule_coro


@dataclass
class LiveDeps:
    fetch_tabs: object = None
    join_tab: object = None
    commit: object = None
    log: object = None
    publish: object = None


@dataclass
class Report:
    added: int = 0
    linked: int = 0
    removed: int = 0
    joined: int = 0
    revived: int = 0
    stale: int = 0
    deferred: int = 0


def update_interval(bridge, value) -> None:
    """One cadence write path for the settings control and its history restore."""
    ms = clamp_interval_ms(value)
    bridge.config.set_state(url_reconcile_interval_ms=ms)
    live_bus(bridge).wake("interval")
    bridge._log(f"URL reconcile interval set to {ms}ms", "info")


def last_pass_at(bridge) -> float:
    return float(getattr(bridge, "_last_reconcile_at", 0) or 0)


def _busy_tabs(bridge) -> set:
    try:
        pool = getattr(bridge, "_page_pool", None)
        if not pool or not getattr(pool, "_pages", None):
            return set()
        return {getattr(p, "tab_id", "") for p in pool._pages.values() if getattr(p, "current_image", None)}
    except Exception:
        return set()


def _pattern(bridge) -> str:
    try:
        return bridge.config.get_state("url_pattern", "") or ""
    except Exception:
        return ""

def _mark(bridge, rows) -> int:
    try:
        from app.services.live.url_policy import connected_tab_ids, mark_receivers
        return int(mark_receivers(rows, enabled_tab_ids(rows), connected_tab_ids(getattr(bridge, "_page_pool", None))) or 0)
    except Exception:
        return 0



def _apply_claim(rows, plan) -> int:
    linked = 0
    by_id = {u.id: u for u in rows}
    for rid, tid in getattr(plan, "claim", []) or []:
        r = by_id.get(rid)
        if r and not getattr(r, "tab_id", ""):
            r.tab_id = tid; linked += 1
    return linked


def _apply_add(bridge, rows, plan) -> int:
    if not getattr(plan, "add", None):
        return 0
    mem = getattr(bridge, "_url_memory", {}) or {}
    before = len(rows); add_rows(rows, plan.add, mem)
    try:
        bridge._url_memory = remember(rows, mem)
    except Exception:
        pass
    return len(rows) - before


def _apply_remove(bridge, rows, removals, deps) -> int:
    if not removals:
        return 0
    rm_ids = {r.row_id for r in removals}
    clear_row_assignments(bridge, rm_ids)
    before = len(rows)
    bridge.state.urls[:] = [u for u in rows if getattr(u, "id", "") not in rm_ids]
    for line in removal_lines(removals):
        try:
            if deps and callable(getattr(deps, "log", None)):
                deps.log(line)
            else:
                bridge._log(line, "info")
        except Exception:
            pass
    return before - len(bridge.state.urls)


async def _join_connect(plan, deps) -> int:
    joined = 0
    for ws in getattr(plan, "connect", []) or []:
        try:
            if callable(deps.join_tab):
                await deps.join_tab(ws)
            joined += 1
        except Exception:
            pass
    return joined


def _maybe_commit(bridge, deps, flag) -> None:
    if not flag:
        return
    try:
        deps.commit() if callable(deps.commit) else (bridge._save_arena(), bridge._emit_arena_state(), live_bus(bridge).wake("urls"))
    except Exception:
        pass


def _log_report(bridge, deps, source, rep) -> None:
    added, linked, joined, removed = rep.added, rep.linked, rep.joined, rep.removed
    if added or linked or joined or removed:
        msg = f"🤖 Auto-connect: +{added} rows, {linked} linked, {joined} joined, 0 revived, 0 stale, {removed} removed"
    elif source == "manual":
        msg = "🤖 Reparse: no changes — rows and pool already match open tabs"
    else:
        return
    try:
        if deps and callable(getattr(deps, "log", None)): deps.log(msg)
        else: bridge._log(msg, "info")
    except Exception:
        pass


# quality-override: cc=11 reason=S6 one-pass diff with dedupe, busy, pattern, misses, plan, mark and join steps kept together per RULE 18.2
# quality-override: loc=32 reason=single reconcile pass that must log and commit atomically, splitting would scatter the 7-step diff
async def reconcile_once(bridge, deps: LiveDeps, source: str) -> Report:
    try:
        tabs = await deps.fetch_tabs() if callable(deps.fetch_tabs) else []
    except Exception as e:
        try:
            msg = f"Auto-connect scan skipped: {e}"
            if deps and callable(getattr(deps, "log", None)): deps.log(msg)
            else: bridge._log(msg, "warn")
        except Exception:
            pass
        return Report()
    if not tabs:
        return Report()
    rows = getattr(bridge.state, "urls", [])
    _, dropped = dedupe_rows(rows)
    if dropped:
        bridge.state.urls[:] = [r for r in rows if r not in dropped]; rows = bridge.state.urls
    live_keys = live_tab_keys(tabs); busy = _busy_tabs(bridge); pattern = _pattern(bridge)
    misses = dict(getattr(bridge, "_reconcile_misses", {}) or {}); removals = removable_rows(RemovalSpec(rows=list(rows), live_keys=live_keys, pattern=pattern, busy_tabs=busy, misses=misses))
    try:
        bridge._reconcile_misses = advance_misses(rows, live_keys, misses)
        plan = plan_auto_connect(tabs, pattern, list(map(asdict, rows)), pooled_ids(getattr(bridge, "_page_pool", None)))
    except Exception:
        plan = None
    linked = _apply_claim(rows, plan); added = _apply_add(bridge, rows, plan); removed = _apply_remove(bridge, rows, removals, deps)
    marked = _mark(bridge, rows)
    joined = await _join_connect(plan, deps)
    need = added + linked + removed + joined + marked + len(dropped)
    _maybe_commit(bridge, deps, need)
    rep = Report(added=added, linked=linked, removed=removed, joined=joined)
    _log_report(bridge, deps, source, rep)
    return rep


def _publish(deps) -> None:
    """Optional observation must never interrupt the reconciler."""
    try:
        if callable(deps.publish):
            deps.publish()
    except Exception:
        pass


async def reconcile_loop(bridge, deps: LiveDeps) -> None:
    bus = live_bus(bridge)
    try:
        bus.attach(asyncio.get_running_loop())
    except RuntimeError:
        pass
    while not getattr(bridge, "_stop_reconcile", False):
        await reconcile_once(bridge, deps, "auto")
        bridge._last_reconcile_at = time.time()
        bridge._reconcile_passes = int(getattr(bridge, "_reconcile_passes", 0) or 0) + 1
        _publish(deps)
        try:
            await bus.wait(interval_ms(bridge) / 1000.0)
        except asyncio.CancelledError:
            break


def start_reconciler(bridge, deps: LiveDeps) -> None:
    if getattr(bridge, "_reconcile_started", False):
        return
    try:
        bridge._reconcile_started = True
    except Exception:
        pass
    try:
        schedule_coro(bridge, reconcile_loop(bridge, deps))
    except Exception:
        pass
