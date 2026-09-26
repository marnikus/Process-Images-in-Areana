"""The row half of one reconcile pass (S6 / D-2 / I-64) — rows follow the fetched tabs.

`sync_rows` runs, in order:
1. dedupe;
2. manual Reparse only: the sweep;
3. linked rows follow their tab's navigation (I-64);
4. plan → claim / add;
5. the removal table (reasons, hysteresis, busy deferral; typed rows are
   unlinked instead of removed, I-64).

It works on the pass object (`reconcile._Pass`) and mutates only the URL rows
and the pass's report/stats. Commit, pool presence and the summary stay in
`reconcile.py`. Split out of `reconcile.py` (2026-09-25, RULE 18.2: the file
passed 400 lines with two responsibilities). Imports: services + core only
(never `app.ui` / `app.browser`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Set

from app.services import auto_connect as ac
from app.services.live import sources as src
from app.services.live import url_policy as up
from app.services.run_state import pooled_ids

if TYPE_CHECKING:
    from app.services.live.reconcile import _Pass

PATTERN_KEY = "url_pattern"
DEFAULT_PATTERN = "arena.ai"


def _survives_sweep(row: Any, busy: Set[str], held: Iterable[str]) -> bool:
    """A manual Reparse keeps a row under a live job, a typed row and a silent browser's row (I-64)."""
    return row.tab_id in busy or bool(getattr(row, "typed", False)) or (bool(row.tab_id) and row.tab_id in held)


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


def _apply_plan(p: _Pass, plan: ac.AutoConnectPlan) -> None:
    """Claim → add → log one line per change (RULE 2)."""
    p.report.linked = _claim_rows(p.urls, plan.claim)
    p.report.added = up.add_rows(p.urls, plan.add, p.stats["memory"])
    for url, tab_id in plan.add:
        p.deps.log(f"🔺 URL added {url} (tab {tab_id}) — new matching tab", "info")
    for row_id, tab_id in plan.claim:
        p.deps.log(f"🔗 URL linked row {row_id} → tab {tab_id} — exact URL match", "info")


def _follow_urls(p: _Pass) -> None:
    """Linked auto rows follow their tab's navigation (one line each, I-64)."""
    moved = src.follow_urls(p.urls, p.tabs, p.pattern)
    for old, new, tab_id in moved:
        p.deps.log(src.follow_line(old, new, tab_id), "info")
    if moved:
        p.bridge._reconcile_unsaved = True   # rows changed in place: the funnel must save them


def _removal_spec(p: _Pass) -> up.RemovalSpec:
    live = src.live_keys(p.tabs)   # + the held keys of a silent browser (I-64)
    p.stats["misses"] = up.advance_misses(p.urls, live, p.stats["misses"])
    linked = [u.tab_id for u in p.urls if u.tab_id]
    return up.RemovalSpec(rows=list(p.urls), live_keys=live, pattern=p.pattern,
                          busy_tabs=up.busy_tabs(getattr(p.bridge, "_page_pool", None), linked),
                          misses=p.stats["misses"])


def _remove_rows(p: _Pass, spec: up.RemovalSpec) -> None:
    """Apply `removable_rows` (typed rows unlink instead, I-64; remember the checkbox, log a reason each)."""
    removals, unlinks = up.split_typed(up.removable_rows(spec), p.urls)
    _unlink_rows(p, unlinks, spec)
    gone = {r.row_id for r in removals}
    up.remember([u for u in p.urls if u.id in gone], p.stats["memory"])
    p.bridge.state.urls = [u for u in p.urls if u.id not in gone]
    for line in up.removal_lines(removals, spec.pattern, spec.miss_threshold):
        p.deps.log(line, "warn")
    p.report.deferred = _log_deferrals(p, spec)
    p.report.removed += len(removals)  # accumulates over the pass (the manual sweep counts too, D-2)
    p.report.removed_ids = sorted(set(p.report.removed_ids) | gone)


def _log_deferrals(p: _Pass, spec: up.RemovalSpec) -> int:
    """One line per deferral streak (a busy tab's row waits for its job); returns how many wait."""
    deferred = up.deferred_rows(spec)
    for d in deferred:
        if d.row_id not in p.stats["deferred_logged"]:
            p.deps.log(f"⏸ URL removal deferred {d.url} — job running on its tab (next reconcile)", "info")
    p.stats["deferred_logged"] = {d.row_id for d in deferred}  # logged once per deferral streak
    return len(deferred)


def _unlink_rows(p: _Pass, unlinks, spec: up.RemovalSpec) -> None:
    """Typed rows keep their place and lose only their tab (never auto-removed, I-64).

    `split_typed` picks unlinks from the CURRENT rows, so each one is present and linked.
    """
    by_id = {u.id: u for u in p.urls}
    for removal in unlinks:
        row = by_id[removal.row_id]
        p.deps.log(up.unlink_line(removal, row.tab_id, spec), "info")
        row.tab_id = ""
        p.bridge._reconcile_unsaved = True   # a row changed in place: the funnel must save it


def _sweep_rows(p: _Pass, spec: up.RemovalSpec) -> None:
    """Manual Reparse (D-2): every row without a live job goes — this pass rebuilds the list from open tabs.

    The checkbox each row had is remembered (`restore_enabled` puts it back
    on the fresh row); rows under a live job keep their identity (RULE 15),
    and so do typed rows and the rows of a browser that stayed silent (I-64).
    """
    held = src.held_rows(p.tabs)
    kept = [u for u in p.urls if _survives_sweep(u, spec.busy_tabs, held)]
    gone = [u for u in p.urls if u not in kept]
    if not gone and not kept:
        return
    up.remember(gone, p.stats["memory"])
    p.report.swept = p.report.removed = len(gone)
    p.report.removed_ids = sorted(u.id for u in gone)
    p.bridge.state.urls = kept
    kept_note = f" ({len(kept)} kept: job running)" if kept else ""
    p.deps.log(f"🧹 Reparse: cleared {len(gone)} URL row(s) — rebuilding from open tabs{kept_note}", "info")


def sync_rows(p: _Pass) -> ac.AutoConnectPlan:
    """Rows follow the fetched tabs: dedupe → (manual: sweep) → plan → claim/add → remove (with reasons)."""
    p.pattern = p.bridge.config.get_state(PATTERN_KEY, DEFAULT_PATTERN)
    spec = _removal_spec(p)  # one spec per pass: misses advance once, the sweep reuses its busy set
    if p.source == "manual":
        _sweep_rows(p, spec)
    rows, duplicates = up.dedupe_rows(p.urls)
    if duplicates:
        p.deps.log(f"🤖 Reconcile: removed {duplicates} extra row(s) — their tab already has a row", "warn")
    _follow_urls(p)
    plan = ac.plan_auto_connect(p.tabs, p.pattern, rows, pooled_ids(getattr(p.bridge, "_page_pool", None)))
    _apply_plan(p, plan)
    _remove_rows(p, spec)
    p.report.removed += duplicates
    return plan
