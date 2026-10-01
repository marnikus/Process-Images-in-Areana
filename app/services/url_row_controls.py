"""URL-list row controls — inline JOBS edit + Reset-all cooldowns.

Owns the URL-row-facing bridge helpers so `panels/url_queue.py` stays thin while
worker state still changes through the canonical pool/tab services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.persistence.cooldown_store import save_job_count
from app.services import tab_reset
from app.services.live.bus import live_bus
from app.services.run_state import cooldowns_path, tab_label_of


@dataclass(frozen=True)
class RowTarget:
    url_id: str
    url: str
    tab_id: str
    label: str


def _rows(bridge: Any):
    return getattr(getattr(bridge, "state", None), "urls", []) or []


def find_row(bridge: Any, url_id: str):
    """URL row by id (None when absent)."""
    return next((row for row in _rows(bridge) if getattr(row, "id", "") == url_id), None)


def row_target(bridge: Any, url_id: str) -> RowTarget | None:
    """URL-row identity + its live worker label, or None when the row has no pooled tab."""
    row = find_row(bridge, url_id)
    pool = getattr(bridge, "_page_pool", None)
    if row is None or not getattr(row, "tab_id", "") or pool is None:
        return None
    page = pool.get_page(row.tab_id)
    if page is None:
        return None
    return RowTarget(url_id=row.id, url=row.url, tab_id=row.tab_id, label=tab_label_of(pool, row.tab_id))


def _whole_non_negative(value: Any) -> int | None:
    """Operator-entered Jobs value, or None when it is invalid."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def set_job_count(bridge: Any, url_id: str, count: Any) -> dict:
    """Inline JOBS edit: update the worker and persist the exact counter."""
    row = find_row(bridge, url_id)
    if row is None:
        return {"ok": False, "error": "row not found"}
    total = _whole_non_negative(count)
    if total is None:
        return {"ok": False, "error": "job count must be a whole non-negative number"}
    target = row_target(bridge, url_id)
    if target is None:
        return {"ok": False, "error": "row tab not in pool"}
    pool = bridge._page_pool
    page = pool.get_page(target.tab_id)
    if page is None:
        return {"ok": False, "error": "row tab not in pool"}
    page.jobs_completed = total
    if not save_job_count(cooldowns_path(bridge), page.url or target.url, total):
        return {"ok": False, "error": "job count persist failed"}
    bridge._emit_pool_status()
    bridge._persist_cooldowns()
    live_bus(bridge).wake("jobs edited")
    bridge._log(f"🔢 Jobs for {target.label} set to {total}", "info")
    return {"ok": True, "jobs_completed": total}


def cooldown_targets(bridge: Any) -> list[RowTarget]:
    """Every current URL row that owns a pooled tab, de-duplicated by tab id."""
    seen, out = set(), []
    for row in _rows(bridge):
        target = row_target(bridge, getattr(row, "id", ""))
        if target is None or target.tab_id in seen:
            continue
        seen.add(target.tab_id)
        out.append(target)
    return out


def reset_all_cooldowns(bridge: Any) -> dict:
    """Global URL-list reset: one bulk clear, one concise reply, URL rows named."""
    targets = cooldown_targets(bridge)
    bulk = tab_reset.clear_many(bridge, [t.tab_id for t in targets])
    failures = _failures_of(targets, bulk)
    ok = bool(bulk.get("ok")) and not failures
    return {"ok": ok, "reset_count": int(bulk.get("reset_count", 0) or 0),
            "failed_rows": failures}


def _failures_of(targets: list[RowTarget], bulk: dict) -> list[dict]:
    """Failed/persist-missed rows in the URL-list reply shape."""
    by_tab = {t.tab_id: t for t in targets}
    rows = _result_failures(by_tab, bulk.get("results", []))
    return rows if bulk.get("persisted", True) else _persist_failures(by_tab, bulk.get("results", []), rows)


def _result_failures(by_tab: dict[str, RowTarget], results: list[dict]) -> list[dict]:
    """Per-tab operation failures (unknown tab, pool missing, etc.)."""
    out = []
    for res in results:
        if res.get("ok"):
            continue
        target = by_tab.get(res.get("tab_id", ""))
        if target is not None:
            out.append(_failure_dict(target, str(res.get("error", "failed"))))
    return out


def _persist_failures(by_tab: dict[str, RowTarget], results: list[dict], failed: list[dict]) -> list[dict]:
    """A failed single persist names every row whose live reset now needs saving."""
    known = {(f["url_id"], f["tab_id"]) for f in failed}
    for res in results:
        if not res.get("ok") or not res.get("changed"):
            continue
        target = by_tab.get(res.get("tab_id", ""))
        key = (target.url_id, target.tab_id) if target else None
        if target is not None and key not in known:
            failed.append(_failure_dict(target, "persist failed"))
    return failed


def _failure_dict(target: RowTarget, error: str) -> dict:
    """Stable failure payload for the web UI + tests."""
    return {"url_id": target.url_id, "url": target.url, "tab_id": target.tab_id,
            "label": target.label, "error": error}
