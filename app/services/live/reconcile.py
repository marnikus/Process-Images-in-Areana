"""The Python-owned URL reconciler (S6, D-4 / D-10 / I-50).

URL rows follow Chrome in EVERY run state at a user-set cadence
(`debug_view.interval_ms`, read every pass). One pass = today's auto-scan
(fetch → dedupe → plan → apply → join → presence) with the idle-only prune
replaced by `url_policy.removable_rows` (reasons, hysteresis, live-job
deferral). A **manual** pass (the Reparse buttons) sweeps first (D-2,
2026-09-21): every row without a live job goes, checkboxes are remembered,
and the same pass rebuilds the list from the fetched tabs — fetch-first, so
a failed fetch never removes. Every pass also enforces the checkbox→pool
gate (D-3/D-4): an unchecked row's tab leaves the pool through
`LiveDeps.leave_tab`, a busy tab defers, and `plan_auto_connect` never
auto-rejoins it while unchecked. Row changes commit through `LiveDeps.commit`
— the UI's URL funnel without an undo entry (system change, I-37) — and wake
the live bus with `urls`. The service never imports `app.ui` or
`app.browser`: the callables it needs arrive in `LiveDeps`.
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
from app.services.live.firefox_badges import assert_firefox_badges
from app.services.live.firefox_owner import resolve_firefox_owners
from app.services.live.tab_owner import resolve_owners
from app.services.live.worker_badges import assert_badges
from app.services.run_state import pooled_ids, schedule_coro

log = logging.getLogger(__name__)
PATTERN_KEY = "url_pattern"
DEFAULT_PATTERN = "arena.ai"


class ScanUnavailable(RuntimeError):
    """The listing pass did not answer — an empty listing is a wait, not a removal.

    `browser_tabs.reconcile_tabs` distinguishes "the browser has no tabs" from
    "the browser said nothing": the second raises this, and `_fetch` turns it into
    a skipped pass (round 8's "a failed fetch is a wait, not a removal" — URL rows
    for tabs that are still open must never age out on a broken pass).
    """


@dataclass
class LiveDeps:
    """The UI-land seam: built by `browser_tabs.live_deps`, injected once."""

    fetch_tabs: Callable[[], Awaitable[Any]]
    join_tab: Callable[[str], Awaitable[Any]]
    commit: Callable[[], Any]
    log: Callable[..., Any]
    leave_tab: Callable[[str], bool] | None = None  # checkbox→pool exit (D-4); None = no pool writes


@dataclass
class Report:
    added: int = 0
    linked: int = 0
    removed: int = 0
    joined: int = 0
    revived: int = 0
    stale: int = 0
    deferred: int = 0
    swept: int = 0
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
    """Pass, then sleep the CURRENT interval (or until `interval`/`start` wakes it) — forever.

    No single pass may end the loop (I-47 shape): a failing pass is logged and
    the next interval retries it, so a transient Chrome/save error can never
    leave the URL list without an owner for the rest of the session.
    """
    bus = live_bus(bridge)
    bus.attach(asyncio.get_running_loop())
    while True:
        await _auto_pass(bridge, deps)
        await bus.wait(interval_ms(bridge) / 1000.0)


async def _auto_pass(bridge, deps: LiveDeps) -> None:
    """One auto pass that survives its own failure; success clears the error memo."""
    try:
        await reconcile_once(bridge, deps, "auto")
    except Exception as e:
        _log_pass_error(bridge, deps, e)
    else:
        bridge._reconcile_last_error = ""


def _log_pass_error(bridge, deps: LiveDeps, e: Exception) -> None:
    """One warn line per distinct failure text (a repeating error never spams the log)."""
    text = f"{type(e).__name__}: {e}"
    if getattr(bridge, "_reconcile_last_error", "") == text:
        return
    bridge._reconcile_last_error = text
    deps.log(f"⚠ Reconcile pass failed ({text}) — loop alive, next pass retries", "warn")


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
    p.report.removed += len(removals)  # accumulates over the pass (the manual sweep counts too, D-2)
    p.report.removed_ids = sorted(set(p.report.removed_ids) | gone)
    p.report.deferred = len(deferred)


def _apply_plan(p: _Pass, plan: ac.AutoConnectPlan) -> None:
    """Claim → add → log one line per change (RULE 2)."""
    p.report.linked = _claim_rows(p.urls, plan.claim)
    p.report.added = up.add_rows(p.urls, plan.add, p.stats["memory"])
    for url, tab_id in plan.add:
        p.deps.log(f"🔺 URL added {url} (tab {tab_id}) — new matching tab", "info")
    for row_id, tab_id in plan.claim:
        p.deps.log(f"🔗 URL linked row {row_id} → tab {tab_id} — exact URL match", "info")


async def _join_each(p: _Pass, sockets) -> int:
    """Join every planned socket; one bad tab never stops the others (D-1)."""
    joined = 0
    for ws in sockets:
        if not ws:
            continue
        try:
            await p.deps.join_tab(ws)
        except Exception as e:
            p.report.error = str(e)
            p.deps.log(f"⚠ Pool join failed ({e}) — next pass retries", "warn")
            continue
        joined += 1
    return joined


async def _join_and_sync(p: _Pass, plan: ac.AutoConnectPlan) -> None:
    p.report.joined += await _join_each(p, plan.connect)
    live = {(getattr(t, "id", "") or getattr(t, "ws_url", "")) for t in p.tabs or []} - {""}
    revived, stale = ac.sync_pool_presence(getattr(p.bridge, "_page_pool", None), live)
    p.report.revived, p.report.stale = revived, len(stale)
    pool = getattr(p.bridge, "_page_pool", None)
    await resolve_owners(pool)   # a navigation can land on another account (D-5)
    await assert_badges(pool)    # a navigation wipes the badge (D-5)
    try:
        await resolve_firefox_owners(pool, bridge=p.bridge)  # Firefox: bounded retry, never blocks
    except Exception:
        pass
    try:
        await assert_firefox_badges(pool, bridge=p.bridge)    # Firefox: centered N# account, idempotent
    except Exception:
        pass


def _publish(p: _Pass, changed: bool) -> None:
    """Persist + wake through the funnel; a failed save stays pending for the next pass.

    Rows and the pool live in the same pass, but only this write reaches the
    UI and the jar: when it fails, the in-memory rebuild would otherwise be
    invisible until an unrelated save happened to publish it (D-1).
    """
    if not (changed or getattr(p.bridge, "_reconcile_unsaved", False)):
        return
    try:
        p.deps.commit()
    except Exception as e:
        p.bridge._reconcile_unsaved = True
        p.report.error = str(e)
        p.deps.log(f"⚠ URL save failed ({e}) — the next pass retries", "error")
        return
    p.bridge._reconcile_unsaved = False
    live_bus(p.bridge).wake("urls")


def _commit(p: _Pass) -> None:
    """Row changes go through the funnel (no undo), dangling image assignments are dropped, the loop wakes."""
    report = p.report
    if report.removed_ids:
        cleared = clear_row_assignments(p.bridge, report.removed_ids)
        if cleared:
            p.deps.log(f"↩ {cleared} image(s) unassigned — their URL row was removed", "info")
    receivers = up.mark_receivers(p.urls, getattr(p.bridge, "_page_pool", None))  # after presence (S7)
    _publish(p, any((report.added, report.linked, report.removed, receivers)))


def _empty_manual_note(p: _Pass) -> str:
    """Why a manual rebuild found nothing (RULE 4: 'nothing matched' must be sayable)."""
    if p.source != "manual" or p.urls or not p.tabs:
        return ""
    return (f"⚠ Reparse: 0 of {len(p.tabs)} open tab(s) match pattern '{p.pattern}' — "
            "check the URL pattern in Settings")


def _summary(p: _Pass) -> None:
    """Manual passes always answer; auto passes only when something changed."""
    r = p.report
    if p.source == "manual":
        note = _empty_manual_note(p)
        if note:
            p.deps.log(note, "warn")
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


def _sync_rows(p: _Pass) -> ac.AutoConnectPlan:
    """Rows follow the fetched tabs: dedupe → (manual: sweep) → plan → claim/add → remove (with reasons)."""
    p.pattern = p.bridge.config.get_state(PATTERN_KEY, DEFAULT_PATTERN)
    spec = _removal_spec(p)  # one spec per pass: misses advance once, the sweep reuses its busy set
    if p.source == "manual":
        _sweep_rows(p, spec)
    rows, duplicates = up.dedupe_rows(p.urls)
    if duplicates:
        p.deps.log(f"🤖 Reconcile: removed {duplicates} extra row(s) — their tab already has a row", "warn")
    plan = ac.plan_auto_connect(p.tabs, p.pattern, rows, pooled_ids(getattr(p.bridge, "_page_pool", None)))
    _apply_plan(p, plan)
    _remove_rows(p, spec)
    p.report.removed += duplicates
    return plan


def _sweep_rows(p: _Pass, spec: up.RemovalSpec) -> None:
    """Manual Reparse (D-2): every row without a live job goes — this pass rebuilds the list from open tabs.

    The checkbox each row had is remembered (`restore_enabled` puts it back
    on the fresh row); rows under a live job keep their identity (RULE 15).
    """
    kept = [u for u in p.urls if u.tab_id in spec.busy_tabs]
    gone = [u for u in p.urls if u not in kept]
    if not gone and not kept:
        return
    up.remember(gone, p.stats["memory"])
    p.report.swept = p.report.removed = len(gone)
    p.report.removed_ids = sorted(u.id for u in gone)
    p.bridge.state.urls = kept
    kept_note = f" ({len(kept)} kept: job running)" if kept else ""
    p.deps.log(f"🧹 Reparse: cleared {len(gone)} URL row(s) — rebuilding from open tabs{kept_note}", "info")


def _enforce_membership(p: _Pass) -> None:
    """The URL list owns pool membership (I-56/I-58): exits leave now, busy ones defer."""
    pool = getattr(p.bridge, "_page_pool", None)
    if pool is None or p.deps.leave_tab is None:
        return
    leaves, deferred = up.pool_exits(p.urls, pool)
    for exit in leaves:
        if p.deps.leave_tab(exit.tab_id):
            p.deps.log(up.exit_line(exit), "info")
    logged = p.stats.setdefault("exit_deferred_logged", set())
    for exit in deferred:
        if exit.tab_id not in logged:
            p.deps.log(up.defer_line(exit), "info")
    p.stats["exit_deferred_logged"] = {e.tab_id for e in deferred}  # once per deferral streak


async def _pool_phase(p: _Pass, plan: ac.AutoConnectPlan) -> None:
    """Join + presence + checkbox gate; a pool failure costs the pool, never the rebuilt rows."""
    try:
        await _join_and_sync(p, plan)
        _enforce_membership(p)
    except Exception as e:
        p.report.error = str(e)
        p.deps.log(f"⚠ Pool update failed ({e}) — URL rows kept, next pass retries", "warn")


async def _pass(p: _Pass) -> Report:
    """fetch → rows (only when Chrome answered tabs) → join + presence → membership → commit → summary."""
    if not await _fetch(p):
        return p.report
    plan = _sync_rows(p) if p.tabs else ac.AutoConnectPlan()  # an empty fetch never touches rows
    await _pool_phase(p, plan)
    _commit(p)
    _summary(p)
    return p.report
