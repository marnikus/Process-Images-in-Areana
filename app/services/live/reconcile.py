"""The Python-owned URL reconciler (S6, D-4 / D-10 / I-50).

URL rows follow Chrome in EVERY run state at a user-set cadence
(`debug_view.interval_ms`, read every pass). One pass = today's auto-scan
(fetch → dedupe → plan → apply → join → presence) with the idle-only prune
replaced by `url_policy.removable_rows` (reasons, hysteresis, live-job
deferral). Row changes commit through `LiveDeps.commit` — the UI's URL
funnel without an undo entry (system change, I-37) — and wake the live bus
with `urls`. The service never imports `app.ui` or `app.browser`: the four
callables it needs arrive in `LiveDeps`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List

from app.services import auto_connect as ac
from app.services.live import url_policy as up
from app.services.live.bus import live_bus
from app.services.live.debug_view import interval_ms
from app.services.live.feed import clear_row_assignments
from app.services.run_state import pooled_ids, schedule_coro

log = logging.getLogger(__name__)
PATTERN_KEY = "url_pattern"
DEFAULT_PATTERN = "arena.ai"


@dataclass
class LiveDeps:
    """The UI-land seam: built by `browser_tabs.live_deps`, injected once."""

    fetch_tabs: Callable[[], Awaitable[Any]]
    join_tab: Callable[[str], Awaitable[Any]]
    commit: Callable[[], Any]
    log: Callable[..., Any]


@dataclass
class Report:
    added: int = 0
    linked: int = 0
    removed: int = 0
    joined: int = 0
    revived: int = 0
    stale: int = 0
    deferred: int = 0
    error: str = ""
    removed_ids: List[str] = field(default_factory=list)

    def changed(self) -> bool:
        return any((self.added, self.linked, self.removed, self.joined, self.revived, self.stale))


def _stats(bridge) -> Dict[str, Any]:
    stats = getattr(bridge, "_reconcile_stats", None)
    if stats is None:
        stats = {"last_pass_at": 0.0, "passes": 0, "misses": {}, "memory": {}, "deferred_logged": set()}
        bridge._reconcile_stats = stats
    return stats


def last_pass_at(bridge) -> float:
    """Wall-clock time of the previous pass (0.0 before the first)."""
    return float(_stats(bridge)["last_pass_at"])


def pass_count(bridge) -> int:
    return int(_stats(bridge)["passes"])


def start_reconciler(bridge, deps: LiveDeps) -> bool:
    """Schedule the loop once on the bg loop; False when it already runs."""
    task = getattr(bridge, "_url_reconciler", None)
    if task is not None and not getattr(task, "done", lambda: True)():
        return False
    bridge._url_reconciler = schedule_coro(bridge, reconcile_loop(bridge, deps))
    return True


async def reconcile_loop(bridge, deps: LiveDeps) -> None:
    """Pass, then sleep the CURRENT interval (or until `interval`/`start` wakes it) — forever."""
    bus = live_bus(bridge)
    bus.attach(asyncio.get_running_loop())
    while True:
        await reconcile_once(bridge, deps, "auto")
        await bus.wait(interval_ms(bridge) / 1000.0)


@dataclass
class _Pass:
    """Everything one pass carries between its steps (RULE 18: one object, not six args)."""

    bridge: Any
    deps: LiveDeps
    source: str
    stats: Dict[str, Any]
    report: Report = field(default_factory=Report)
    tabs: Any = None
    pattern: str = DEFAULT_PATTERN

    @property
    def urls(self) -> list:
        return self.bridge.state.urls


def _claim_rows(urls: list, claims) -> int:
    """Link unlinked rows to their tabs; returns how many changed."""
    by_id = {u.id: u for u in urls}
    linked = 0
    for row_id, tab_id in claims:
        row = by_id.get(row_id)
        if row is not None and not row.tab_id:
            row.tab_id = tab_id
            linked += 1
    return linked


def _removal_spec(p: _Pass) -> up.RemovalSpec:
    live = ac.live_tab_keys(p.tabs)
    p.stats["misses"] = up.advance_misses(p.urls, live, p.stats["misses"])
    linked = [u.tab_id for u in p.urls if u.tab_id]
    return up.RemovalSpec(rows=list(p.urls), live_keys=live, pattern=p.pattern,
                          busy_tabs=up.busy_tabs(getattr(p.bridge, "_page_pool", None), linked),
                          misses=p.stats["misses"])


def _remove_rows(p: _Pass, spec: up.RemovalSpec) -> None:
    """Apply `removable_rows` (remember the checkbox, log a reason each) and log deferrals once."""
    removals = up.removable_rows(spec)
    gone = {r.row_id for r in removals}
    up.remember([u for u in p.urls if u.id in gone], p.stats["memory"])
    p.bridge.state.urls = [u for u in p.urls if u.id not in gone]
    for line in up.removal_lines(removals, spec.pattern, spec.miss_threshold):
        p.deps.log(line, "warn")
    deferred = up.deferred_rows(spec)
    for d in deferred:
        if d.row_id not in p.stats["deferred_logged"]:
            p.deps.log(f"⏸ URL removal deferred {d.url} — job running on its tab (next reconcile)", "info")
    p.stats["deferred_logged"] = {d.row_id for d in deferred}  # logged once per deferral streak
    p.report.removed, p.report.removed_ids, p.report.deferred = len(removals), sorted(gone), len(deferred)


def _apply_plan(p: _Pass, plan: ac.AutoConnectPlan) -> None:
    """Claim → add → log one line per change (RULE 2)."""
    p.report.linked = _claim_rows(p.urls, plan.claim)
    p.report.added = up.add_rows(p.urls, plan.add, p.stats["memory"])
    for url, tab_id in plan.add:
        p.deps.log(f"🔺 URL added {url} (tab {tab_id}) — new matching tab", "info")
    for row_id, tab_id in plan.claim:
        p.deps.log(f"🔗 URL linked row {row_id} → tab {tab_id} — exact URL match", "info")


async def _join_and_sync(p: _Pass, plan: ac.AutoConnectPlan) -> None:
    for ws in plan.connect:
        if ws:
            await p.deps.join_tab(ws)
            p.report.joined += 1
    live = {(getattr(t, "id", "") or getattr(t, "ws_url", "")) for t in p.tabs or []} - {""}
    revived, stale = ac.sync_pool_presence(getattr(p.bridge, "_page_pool", None), live)
    p.report.revived, p.report.stale = revived, len(stale)


def _commit(p: _Pass) -> None:
    """Row changes go through the funnel (no undo), dangling image assignments are dropped, the loop wakes."""
    report = p.report
    if report.removed_ids:
        cleared = clear_row_assignments(p.bridge, report.removed_ids)
        if cleared:
            p.deps.log(f"↩ {cleared} image(s) unassigned — their URL row was removed", "info")
    if report.added or report.linked or report.removed:
        p.deps.commit()
        live_bus(p.bridge).wake("urls")


def _summary(p: _Pass) -> None:
    """Manual passes always answer; auto passes only when something changed."""
    r = p.report
    if not r.changed():
        if p.source == "manual":
            p.deps.log("🤖 Reparse: no changes — rows and pool already match open tabs", "info")
        return
    p.deps.log(f"🤖 Reconcile: +{r.added} added, {r.linked} linked, −{r.removed} removed, "
               f"{r.joined} joined, {r.revived} revived, {r.stale} stale", "info")


async def reconcile_once(bridge, deps: LiveDeps, source: str) -> Report:
    """One pass (loop, `auto_connect_scan` slot, Reparse); overlapping passes are skipped."""
    if getattr(bridge, "_auto_scan_running", False):
        return Report(error="busy")
    bridge._auto_scan_running = True
    try:
        return await _pass(_Pass(bridge, deps, source, _stats(bridge)))
    finally:
        bridge._auto_scan_running = False


async def _fetch(p: _Pass) -> bool:
    """Fill `p.tabs`; False (and a warn line) on failure — a failed fetch is a wait, not a removal."""
    try:
        p.tabs = await p.deps.fetch_tabs()
    except Exception as e:
        p.report.error = str(e)
        p.deps.log(f"🤖 Reconcile skipped: {e}", "warn")
        return False
    p.stats["passes"], p.stats["last_pass_at"] = p.stats["passes"] + 1, time.time()
    return True


async def _pass(p: _Pass) -> Report:
    """fetch → dedupe → plan → apply → remove → join → commit; an empty fetch never removes."""
    if not await _fetch(p):
        return p.report
    if not p.tabs:
        _summary(p)
        return p.report
    p.pattern = p.bridge.config.get_state(PATTERN_KEY, DEFAULT_PATTERN)
    rows, duplicates = up.dedupe_rows(p.urls)
    if duplicates:
        p.deps.log(f"🤖 Reconcile: removed {duplicates} extra row(s) — their tab already has a row", "warn")
    plan = ac.plan_auto_connect(p.tabs, p.pattern, rows, pooled_ids(getattr(p.bridge, "_page_pool", None)))
    _apply_plan(p, plan)
    _remove_rows(p, _removal_spec(p))
    p.report.removed += duplicates
    await _join_and_sync(p, plan)
    _commit(p)
    _summary(p)
    return p.report
