"""Python-owned URL reconciler (S6, D-12R) — the JS 15 s timer's replacement.

One loop per bridge, cadence from config read EVERY pass (never cached, bus-wakable);
one pass = fetch tabs → removal table (hysteresis/reasons/deferral) → claim/add →
join pool → presence → commit + wake("urls"). Empty fetches keep every row.
`LiveDeps` is the seam that keeps the services lane free of ui/browser imports.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.services import auto_connect as ac
from app.services.live import debug_view, url_policy
from app.services.live.bus import live_bus


@dataclass
class LiveDeps:
    """UI-wired callables injected by `panels/browser_tabs.live_deps` (round-1 D-10)."""
    fetch_tabs: Callable[[], Awaitable[list]]
    join_tab: Callable[[str], Awaitable[Any]]
    commit: Callable[[], None]
    log: Callable[[str, str], None]


@dataclass
class Report:
    """One reconcile pass's effect (fed to logs, settings and S9's cadence view)."""
    added: int = 0
    linked: int = 0
    removed: int = 0
    joined: int = 0
    revived: int = 0
    stale: int = 0
    deferred: int = 0
    flags: int = 0


def _busy_tab_ids(pool) -> set:
    """Tabs with a live job (current_image set) — their rows defer removal (RULE 15)."""
    try:
        pages, lock = pool._pages, pool._lock
    except AttributeError:
        return set()
    with lock:
        return {tid for tid, page in pages.items() if getattr(page, "current_image", None)}


def _pooled_ids(pool) -> set:
    """Tab ids the pool already owns."""
    try:
        pages, lock = pool._pages, pool._lock
    except AttributeError:
        return set()
    with lock:
        return set(pages.keys())


def last_pass_at(bridge) -> float:
    """Timestamp of the previous pass (0 before the first)."""
    return float(getattr(bridge, "_last_url_pass", 0.0))


def passes(bridge) -> int:
    """Passes observed since boot (manual or loop)."""
    return int(getattr(bridge, "_url_pass_count", 0))


def _memory(bridge) -> dict:
    """Per-bridge remembered checkboxes (bounded, URL-keyed; never persisted)."""
    memory = getattr(bridge, "_url_checkbox_mem", None)
    if memory is None:
        memory = bridge._url_checkbox_mem = {}
    return memory


def _apply_removals(bridge, removals, memory) -> None:
    """Remember the checkbox by URL, then drop the rows (with reason lines)."""
    gone = {r.row_id for r in removals}
    by_id = {u.id: u for u in bridge.state.urls}
    for removal in removals:
        row = by_id.get(removal.row_id)
        if row is not None:
            url_policy.remember(memory, row.url, row.enabled)
    bridge.state.urls[:] = [u for u in bridge.state.urls if u.id not in gone]


def _apply_claims(bridge, claims, memory) -> int:
    """Link unlinked rows to their tabs; the remembered checkbox is restored."""
    by_id = {u.id: u for u in bridge.state.urls}
    linked = 0
    for row_id, tab_id in claims or []:
        row = by_id.get(row_id)
        if row is not None and not row.tab_id:
            row.tab_id = tab_id
            url_policy.restore_enabled(row, memory)
            linked += 1
    return linked


def _apply_adds(bridge, adds, memory) -> int:
    """Append rows for freshly seen tabs; remembered checkbox restored."""
    added = url_policy.add_rows(bridge.state.urls, adds)
    if added:
        for row in bridge.state.urls[-added:]:
            url_policy.restore_enabled(row, memory)
    return added


async def _join_all(deps: LiveDeps, sockets) -> int:
    """Pool-join each live socket; skips empties."""
    joined = 0
    for ws in sockets or []:
        if ws:
            await deps.join_tab(ws)
            joined += 1
    return joined


def _row_dicts(rows) -> list:
    """Planner-view of the kept rows (plan_auto_connect's dict contract)."""
    return [{"id": u.id, "url": u.url, "tab_id": u.tab_id, "enabled": u.enabled}
            for u in rows or []]


def _report_line(rep: Report) -> str:
    """One summary line, same vocabulary as the old auto-connect report (RULE 2)."""
    return (f"🤖 Auto-connect: +{rep.added} rows, {rep.linked} linked, "
            f"{rep.joined} joined, {rep.revived} revived, {rep.stale} stale, "
            f"{rep.removed} removed")


async def reconcile_once(bridge, deps: LiveDeps, source: str = "auto") -> Report:
    """One pass: fetch → removal table → claim/add → join → presence → commit + wake."""
    tabs = await deps.fetch_tabs()
    bridge._last_url_pass = time.time()        # every pass attempt is recorded
    bridge._url_pass_count = passes(bridge) + 1
    if not tabs:
        return Report()                        # empty fetch keeps every row (safety)
    pattern = bridge.config.get_state("url_pattern", "arena.ai")
    live_keys = ac.live_tab_keys(tabs)
    memory = _memory(bridge)
    rows = list(getattr(bridge.state, "urls", []) or [])
    misses = url_policy.advance_misses(rows, live_keys, getattr(bridge, "_url_misses", {}))
    bridge._url_misses = misses
    spec = url_policy.RemovalSpec(rows=rows, live_keys=live_keys, pattern=pattern,
                                  busy_tabs=_busy_tab_ids(bridge._page_pool), misses=misses)
    removals = url_policy.removable_rows(spec)
    _apply_removals(bridge, removals, memory)
    clean, _dropped = url_policy.dedupe_rows(_row_dicts(bridge.state.urls))
    plan = ac.plan_auto_connect(tabs, pattern, clean, _pooled_ids(getattr(bridge, "_page_pool", None)))
    added, linked = _apply_adds(bridge, plan.add, memory), _apply_claims(bridge, plan.claim, memory)
    revived, stale = ac.sync_pool_presence(getattr(bridge, "_page_pool", None), live_keys)
    joined = await _join_all(deps, plan.connect)
    pool = getattr(bridge, "_page_pool", None)
    flags = url_policy.mark_receivers(bridge.state.urls, url_policy.allowed_tab_ids(bridge.state.urls), pool)
    rep = Report(added=added, linked=linked, removed=len(removals), joined=joined,
                 revived=revived, stale=len(stale), deferred=len(spec.deferred), flags=flags)
    for line in url_policy.removal_lines(removals):
        deps.log(line, "info")
    _commit_and_log(bridge, deps, rep, source)
    return rep


def _commit_and_log(bridge, deps: LiveDeps, rep: Report, source: str) -> None:
    """Commit + wake("urls") on change (flags count as change), then one summary/manual-quiet line (I-37)."""
    changed = rep.added or rep.linked or rep.removed or rep.joined or rep.revived or rep.stale
    if changed or rep.flags:
        deps.commit()
        live_bus(bridge).wake("urls")
    if changed:
        deps.log(_report_line(rep), "info")
    elif source == "manual":
        deps.log("🤖 Reparse: no changes — rows and pool already match open tabs", "info")


async def reconcile_loop(bridge, deps: LiveDeps) -> None:
    """The single periodic writer (RULE 10): pass → wait the config cadence (wakable)."""
    while True:
        try:
            await reconcile_once(bridge, deps, "auto")
        except asyncio.CancelledError:
            raise
        except Exception as exc:                       # RULE 4: loud, loop survives
            deps.log(f"URL reconcile failed: {exc}", "warn")
        await live_bus(bridge).wait(debug_view.interval_ms(bridge) / 1000.0)


def start_reconciler(bridge, deps: LiveDeps) -> None:
    """Idempotent boot start (mirror of the watcher loop's guard)."""
    if getattr(bridge, "_url_reconciler_started", False):
        return
    bridge._url_reconciler_started = True
    from app.services.run_state import schedule_coro
    schedule_coro(bridge, reconcile_loop(bridge, deps))
