"""Row steps of one reconcile pass — the URL list follows the fetched tabs.

Split out of `live/reconcile.py` (RULE 18, 2026-09-27): claim → add → remove
with named reasons (`url_policy.removable_rows`), dedupe, and the manual
Reparse sweep. Each step reads/writes the pass object `reconcile._Pass`
(rows = `bridge.state.urls`, report, stats); the loop, the pool phase and
publishing stay in `reconcile.py`. Imports: services only — never `app.ui`
or `app.browser`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services import auto_connect as ac
from app.services.live import url_policy as up
from app.services.live.listing import held_keys
from app.services.run_state import pooled_ids

if TYPE_CHECKING:
    from app.services.live.reconcile import _Pass

PATTERN_KEY = "url_pattern"
DEFAULT_PATTERN = "arena.ai"


def claim_rows(urls: list, claims) -> int:
    """Link unlinked rows to their tabs; returns how many changed."""
    by_id = {u.id: u for u in urls}
    linked = 0
    for row_id, tab_id in claims:
        row = by_id.get(row_id)
        if row is not None and not row.tab_id:
            row.tab_id = tab_id
            linked += 1
    return linked


def removal_spec(p: "_Pass") -> up.RemovalSpec:
    live = ac.live_tab_keys(p.tabs) | held_keys(p.tabs)   # held = present, never "missing"
    p.stats["misses"] = up.advance_misses(p.urls, live, p.stats["misses"])
    linked = [u.tab_id for u in p.urls if u.tab_id]
    return up.RemovalSpec(rows=list(p.urls), live_keys=live, pattern=p.pattern,
                          busy_tabs=up.busy_tabs(getattr(p.bridge, "_page_pool", None), linked),
                          misses=p.stats["misses"])


def remove_rows(p: "_Pass", spec: up.RemovalSpec) -> None:
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


def apply_plan(p: "_Pass", plan: ac.AutoConnectPlan) -> None:
    """Claim → add → log one line per change (RULE 2)."""
    p.report.linked = claim_rows(p.urls, plan.claim)
    p.report.added = up.add_rows(p.urls, plan.add, p.stats["memory"])
    for url, tab_id in plan.add:
        p.deps.log(f"🔺 URL added {url} (tab {tab_id}) — new matching tab", "info")
    for row_id, tab_id in plan.claim:
        p.deps.log(f"🔗 URL linked row {row_id} → tab {tab_id} — exact URL match", "info")


def sync_rows(p: "_Pass") -> ac.AutoConnectPlan:
    """Rows follow the fetched tabs: dedupe → (manual: sweep) → plan → claim/add → remove (with reasons)."""
    p.pattern = p.bridge.config.get_state(PATTERN_KEY, DEFAULT_PATTERN)
    spec = removal_spec(p)  # one spec per pass: misses advance once, the sweep reuses its busy set
    if p.source == "manual":
        sweep_rows(p, spec)
    rows, duplicates = up.dedupe_rows(p.urls)
    if duplicates:
        p.deps.log(f"🤖 Reconcile: removed {duplicates} extra row(s) — their tab already has a row", "warn")
    plan = ac.plan_auto_connect(p.tabs, p.pattern, rows, pooled_ids(getattr(p.bridge, "_page_pool", None)))
    apply_plan(p, plan)
    remove_rows(p, spec)
    p.report.removed += duplicates
    return plan


def _sweep_keeps(p: "_Pass", spec: up.RemovalSpec) -> tuple:
    """(busy, held) tab keys the sweep must keep.

    busy = a live job on the tab — only while a run is live (a flag left over
    from an ended run never pins a row); held = the browser did not answer.
    """
    running = getattr(p.bridge, "_run_state", "idle") != "idle"
    return (set(spec.busy_tabs) if running else set()), held_keys(p.tabs)


def _kept_note(busy: int, held: int) -> str:
    reasons = [f"{busy} job running"] * bool(busy) + [f"{held} browser not answering"] * bool(held)
    return f" (kept: {', '.join(reasons)})" if reasons else ""


def sweep_rows(p: "_Pass", spec: up.RemovalSpec) -> None:
    """Manual Reparse (D-2): every row without a live job goes — this pass rebuilds the list from open tabs.

    The checkbox each row had is remembered (`restore_enabled` puts it back
    on the fresh row); rows under a live job keep their identity (RULE 15).
    """
    busy, held = _sweep_keeps(p, spec)
    kept = [u for u in p.urls if u.tab_id and u.tab_id in busy | held]
    gone = [u for u in p.urls if u not in kept]
    if not gone and not kept:
        return
    up.remember(gone, p.stats["memory"])
    p.report.swept = p.report.removed = len(gone)
    p.report.removed_ids = sorted(u.id for u in gone)
    p.bridge.state.urls = kept
    note = _kept_note(sum(u.tab_id in busy for u in kept), sum(u.tab_id in held for u in kept))
    p.deps.log(f"🧹 Reparse: cleared {len(gone)} URL row(s) — rebuilding from open tabs{note}", "info")
