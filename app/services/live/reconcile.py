"""URL-row reconciler — Python owns the cadence (S6, D-11 / I-50).

One pass (`reconcile_once`) = what `browser_tabs.auto_scan_pass` used to
do, plus reasons: fetch tabs → repair duplicates → plan (the untouched
`auto_connect` planner) → claim / add rows → decide removals
(`url_policy.removable_rows`, hysteresis, live-job deferral) → commit
through the injected `deps.commit` + `wake("urls")` → join new tabs through
the injected `deps.join_tab` (S1's repaired path) → pool presence → report.
The loop (`reconcile_loop`) waits on its own bus for `interval_ms` (read
every pass) or an early wake (`apply_url_interval`, the manual buttons).
An empty or failed fetch never removes anything.

`LiveDeps` is the seam: services never import panels or the browser layer.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.services import auto_connect as ac
from app.services.run_state import pooled_ids, schedule_coro

from . import url_policy as up
from .bus import LiveBus, live_bus
from .debug_view import interval_ms
from .feed import clear_row_assignments


@dataclass
class LiveDeps:
    """Injected by ui land (`browser_tabs.live_deps`)."""

    fetch_tabs: Callable[[], Awaitable[Any]]
    join_tab: Callable[[str], Awaitable[Any]]
    commit: Callable[[Any], None]
    log: Callable[[str, str], None]


@dataclass
class Report:
    added: int = 0
    linked: int = 0
    removed: int = 0
    joined: int = 0
    revived: int = 0
    stale: int = 0
    deferred: int = 0
    removals: list = field(default_factory=list)

    def changed(self) -> bool:
        """Rows were written (⇒ commit + wake)."""
        return bool(self.added or self.linked or self.removed)

    def pool_touched(self) -> bool:
        """The pool view moved (⇒ emit pool status)."""
        return bool(self.joined or self.revived or self.stale or self.removed)

    def noteworthy(self) -> bool:
        """Anything an auto pass should say out loud."""
        return self.changed() or self.pool_touched()


@dataclass
class ReconcileState:
    """Per-bridge loop memory: miss counters, remembered checkboxes, cadence facts."""

    misses: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    last_pass_at: float = 0.0
    passes: int = 0


def reconcile_state(bridge: Any) -> ReconcileState:
    state = getattr(bridge, "_url_reconcile", None)
    if state is None:
        state = bridge._url_reconcile = ReconcileState()
    return state


def url_bus(bridge: Any) -> LiveBus:
    """The reconciler's own wake event (the run loop's bus has one waiter already)."""
    bus = getattr(bridge, "_url_bus", None)
    if bus is None:
        bus = bridge._url_bus = LiveBus()
    return bus


def last_pass_at(bridge: Any) -> float:
    return reconcile_state(bridge).last_pass_at


async def _fetch(deps: LiveDeps) -> Optional[list]:
    """The tab list, or None when Chrome could not be asked (nothing is removed then)."""
    try:
        return list(await deps.fetch_tabs() or [])
    except Exception as e:
        deps.log(f"Auto-connect scan skipped: {e}", "warn")
        return None


def _claim(bridge: Any, claims: list) -> int:
    by_id = {u.id: u for u in bridge.state.urls}
    linked = 0
    for row_id, tab_id in claims:
        row = by_id.get(row_id)
        if row is not None and not row.tab_id:
            row.tab_id = tab_id
            linked += 1
    return linked


def _forget_rows(bridge: Any, rows: list, gone: set) -> None:
    """Drop removed rows, remembering their checkbox and clearing dangling image assignments."""
    if not gone:
        return
    memory = reconcile_state(bridge).memory
    for row in rows:
        if row.get("id") in gone:
            up.remember(memory, row)
    bridge.state.urls = [u for u in bridge.state.urls if u.id not in gone]
    clear_row_assignments(bridge, gone)


def _remove(bridge: Any, tabs: list, live: set, rows: list) -> tuple[list, int]:
    """Removals with reasons (none on an empty fetch); returns (removals, deferred count)."""
    if not tabs:
        return [], 0
    state = reconcile_state(bridge)
    state.misses = up.advance_misses(rows, live, state.misses)
    spec = up.RemovalSpec(rows=rows, live_keys=live, pattern=bridge.config.get_state("url_pattern", "arena.ai"),
                          busy_tabs=up.busy_tabs(getattr(bridge, "_page_pool", None)), misses=state.misses)
    removals = up.removable_rows(spec)
    _forget_rows(bridge, rows, {r.row_id for r in removals})
    return removals, len(spec.deferred)


async def _join(deps: LiveDeps, sockets: list) -> int:
    joined = 0
    for ws in sockets or []:
        if ws:
            await deps.join_tab(ws)
            joined += 1
    return joined


def _summary(report: Report) -> str:
    deferred = f", {report.deferred} deferred (job running)" if report.deferred else ""
    return (f"🤖 Auto-connect: +{report.added} rows, {report.linked} linked, {report.joined} joined, "
            f"{report.revived} revived, {report.stale} stale, {report.removed} removed{deferred}")


def _report(bridge: Any, deps: LiveDeps, report: Report, source: str) -> None:
    """Manual scans always answer; auto passes speak only on change (plus one line per removal)."""
    for line in up.removal_lines(report.removals):
        deps.log(line, "warn")
    if not report.noteworthy():
        if source == "manual":
            deps.log("🤖 Reparse: no changes — rows and pool already match open tabs", "info")
        return
    if report.pool_touched():
        bridge._emit_pool_status()
    deps.log(_summary(report), "info")


async def reconcile_once(bridge: Any, deps: LiveDeps, source: str) -> Report:
    """One pass: tabs → rows (claim / add / remove with reasons) → commit + wake → join → presence."""
    tabs = await _fetch(deps)
    if tabs is None:
        return Report()
    state = reconcile_state(bridge)
    rows, dupes = up.dedupe_rows(bridge.state.urls)
    plan = ac.plan_auto_connect(tabs, bridge.config.get_state("url_pattern", "arena.ai"), rows,
                                pooled_ids(getattr(bridge, "_page_pool", None)))
    report = Report(linked=_claim(bridge, plan.claim), added=up.add_rows(bridge.state.urls, plan.add, state.memory))
    live = ac.live_tab_keys(tabs)
    report.removals, report.deferred = _remove(bridge, tabs, live, rows)
    report.removed = len(report.removals) + dupes
    if report.changed():
        deps.commit(bridge)
        live_bus(bridge).wake("urls")
    report.joined = await _join(deps, plan.connect)
    report.revived, stale = ac.sync_pool_presence(getattr(bridge, "_page_pool", None), live)
    report.stale = len(stale)
    _report(bridge, deps, report, source)
    state.last_pass_at, state.passes = time.time(), state.passes + 1
    return report


async def reconcile_loop(bridge: Any, deps: LiveDeps) -> None:
    """Forever: wait `interval_ms` (re-read every turn) or an early wake, then one pass."""
    bus = url_bus(bridge)
    while True:
        reason = await bus.wait(interval_ms(bridge) / 1000.0)
        await reconcile_once(bridge, deps, reason or "interval")


def start_reconciler(bridge: Any, deps: LiveDeps) -> bool:
    """Start the loop once per bridge on the bg asyncio loop; False when it is already running."""
    fut = getattr(bridge, "_url_reconciler", None)
    if fut is not None and not fut.done():
        return False
    bridge._url_reconciler = schedule_coro(bridge, reconcile_loop(bridge, deps))
    return bridge._url_reconciler is not None
