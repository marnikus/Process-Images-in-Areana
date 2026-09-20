"""S6: the URL reconciler — one pass syncs rows + pool with the open tabs.

Pure-ish: the pass itself only touches rows via injected LiveDeps, so tests
drive it without a window. One pass: fetch tabs, dedupe rows, plan adds /
claims / joins / removals, commit through the single row funnel, pool-join,
sync presence, report. ``source`` is "auto" (silent unless changed) or
"manual" (always answers).
"""

import asyncio
from dataclasses import dataclass

from app.services.auto_connect import live_tab_keys, plan_auto_connect, sync_pool_presence
from app.services.cooldown_service import tab_has_live_job
from app.services.live import url_policy as up
from app.services.live.bus import live_bus
from app.services.live.debug_view import interval_ms
from app.services.run_state import pooled_ids


@dataclass
class LiveDeps:
    """The four seams a pass needs; panels wire the real ones."""

    fetch_tabs: object
    join_tab: object
    commit: object
    log: object


@dataclass
class Report:
    """What one pass did — the S9 handoff rides these counts."""

    added: int = 0
    linked: int = 0
    removed: int = 0
    joined: int = 0
    revived: int = 0
    stale: int = 0


def _misses_of(bridge):
    misses = getattr(bridge, "_reconcile_misses", None)
    if misses is None:
        misses = {}
        bridge._reconcile_misses = misses
    return misses


def _memory_of(bridge):
    memory = getattr(bridge, "_url_memory", None)
    if memory is None:
        memory = {}
        bridge._url_memory = memory
    return memory


def _busy_tabs(bridge, rows):
    """Row tabs holding a live job — keyed on rows, not the fetch.

    Only absent tabs consult this set (tab_gone), and an absent tab is by
    definition not in the fetch; keying on the fetch would never defer.
    """
    pool = getattr(bridge, "_page_pool", None)
    keys = {up.row_tab(r) for r in rows or []} - {""}
    return {k for k in keys if tab_has_live_job(pool, k)}


async def _fetch_tabs(deps):
    """Fetch, tolerating a down CDP (None + the skip line)."""
    try:
        return await deps.fetch_tabs()
    except Exception as e:
        deps.log(f"Auto-connect scan skipped: {e}", "warn")
        return None


def _claim_rows(by_id, claims):
    """Link unlinked rows to their tabs; returns count linked."""
    linked = 0
    for row_id, tab_id in claims:
        row = by_id.get(row_id)
        if row is not None and not row.tab_id:
            row.tab_id = tab_id
            linked += 1
    return linked


def _drop_rows(bridge, removals):
    """Bank the checkboxes, drop the rows; returns count removed."""
    if not removals:
        return 0
    memory = _memory_of(bridge)
    gone = {r.row_id for r in removals}
    for u in bridge.state.urls:
        if u.id in gone:
            up.remember(u.tab_id, u.enabled, memory)
    before = len(bridge.state.urls)
    bridge.state.urls = [u for u in bridge.state.urls if u.id not in gone]
    return before - len(bridge.state.urls)


async def _join_sockets(deps, sockets):
    """Pool-join each socket; skips empties; returns count joined."""
    joined = 0
    for ws in sockets or []:
        if ws:
            await deps.join_tab(ws)
            joined += 1
    return joined


def _changed(report):
    """True when the pass produced anything worth reporting."""
    return any((report.added, report.linked, report.removed,
                report.joined, report.revived, report.stale))


def _summary_line(report):
    return (f"🤖 Auto-connect: +{report.added} rows, {report.linked} linked, "
            f"{report.joined} joined, {report.revived} revived, "
            f"{report.stale} stale, {report.removed} removed")


def _report(deps, report, removals, source):
    """Removal lines always; the summary answers manual, auto only on change."""
    for line in up.removal_lines(removals):
        deps.log(line, "info")
    if not _changed(report):
        if source == "manual":
            deps.log("🤖 Reparse: no changes — rows and pool already match open tabs", "info")
        return
    deps.log(_summary_line(report), "info")


def _plan_pass(bridge, tabs, rows, live):
    """(plan, removals): what this pass will add/claim/join/remove."""
    pattern = bridge.config.get_state("url_pattern", "arena.ai")
    plan = plan_auto_connect(tabs, pattern, rows, pooled_ids(bridge._page_pool))
    misses = up.advance_misses(bridge.state.urls, live, _misses_of(bridge))
    bridge._reconcile_misses = misses
    removals = up.removable_rows(up.RemovalSpec(
        rows=bridge.state.urls, live_keys=live, pattern=pattern,
        busy_tabs=_busy_tabs(bridge, bridge.state.urls), misses=misses))
    return plan, removals


def _apply_row_changes(bridge, deps, plan, removals):
    """Claim/add/drop rows; commit + wake when changed; returns the counts."""
    by_id = {u.id: u for u in bridge.state.urls}
    linked = _claim_rows(by_id, plan.claim)
    added = up.add_rows(bridge.state.urls, plan.add, _memory_of(bridge))
    removed = _drop_rows(bridge, removals)
    if added or linked or removed:
        deps.commit()
        live_bus(bridge).wake("urls")
    return added, linked, removed


async def reconcile_once(bridge, deps, source="auto"):
    """One pass; returns the Report (empty + logged when the fetch fails)."""
    tabs = await _fetch_tabs(deps)
    if tabs is None:
        return Report()
    rows, deduped = up.dedupe_rows(bridge.state.urls)
    if deduped:  # legacy broken state: N rows on one tab -> keep one (I-33)
        deps.log(f"🤖 Auto-connect: removed {deduped} extra row(s) — their tab already has a row", "warn")
    live = live_tab_keys(tabs)
    plan, removals = _plan_pass(bridge, tabs, rows, live)
    report = Report()
    report.added, report.linked, report.removed = _apply_row_changes(bridge, deps, plan, removals)
    report.joined = await _join_sockets(deps, plan.connect)
    report.revived, stale = sync_pool_presence(bridge._page_pool, live)
    report.stale = len(stale)
    _report(deps, report, removals, source)
    return report


async def reconcile_loop(bridge, deps):
    """Sleep the user interval, reconcile, repeat; skips while a scan runs."""
    while True:
        await asyncio.sleep(interval_ms(bridge) / 1000.0)
        if bridge._auto_scan_running:
            continue
        bridge._auto_scan_running = True
        try:
            await reconcile_once(bridge, deps, "auto")
        finally:
            bridge._auto_scan_running = False
