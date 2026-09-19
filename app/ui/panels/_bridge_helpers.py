"""Shared bridge panel helpers (module functions, no Bridge import)."""

from __future__ import annotations

try:
    from PySide6.QtCore import QObject, Signal, Slot
    _qt_core = True
except ImportError:
    _qt_core = False

if not _qt_core:  # headless shim (no PySide6) — exercised by tests/test_qt_shim_fallback.py
    class QObject:
        def __init__(self, *qt_shim_args, **qt_shim_kwargs): pass

    def Signal(*sig_shim_args, **sig_shim_kwargs):
        class _Sig:
            def emit(self, *emit_shim_args, **emit_shim_kwargs): pass
            def connect(self, *connect_shim_args, **connect_shim_kwargs): pass
        return _Sig()

    def Slot(*slot_shim_args, **slot_shim_kwargs):
        def deco(fn): return fn
        return deco

try:
    from PySide6.QtWidgets import QFileDialog
except ImportError:
    QFileDialog = None

from app.core.models import UrlRow

def _checked_tabs_ready(bridge) -> set:
    """Rescue-claim checked unlinked rows; tab ids usable for runs."""
    from app.services.auto_connect import claim_unlinked_from_pool, enabled_tab_ids
    try:
        pool = bridge._page_pool
        pages = pool.status_snapshot().get("pages", []) if pool else []
        if claim_unlinked_from_pool(bridge.state.urls, pages):
            bridge._save_arena()
    except Exception:
        pass
    return enabled_tab_ids(bridge._get_enabled_urls())

_URL_GATE_MSG = {
    "no enabled urls": ("⚠ No enabled URLs — check a URL row to use it for jobs", "warn"),
    "no checked url linked to a tab": (
        "❌ No checked URL is linked to a live tab — press Reparse or Connect on a checked row first",
        "error"),
}

def _urls_gate_error(bridge, urls) -> str:
    """Start gate: checked URLs must exist and own live tabs (I-33)."""
    if not urls:
        return "no enabled urls"
    if not _checked_tabs_ready(bridge):
        return "no checked url linked to a tab"
    return ""

def _dedupe_state_rows(state_urls) -> tuple[list, int]:
    """Repair legacy N-rows-per-tab state; returns (plan rows, removed)."""
    from app.services.auto_connect import dedupe_linked_rows
    rows = [{"id": u.id, "url": u.url, "tab_id": u.tab_id, "enabled": u.enabled}
            for u in state_urls]
    kept, dropped = dedupe_linked_rows(rows)
    if not dropped:
        return rows, 0
    drop = {r["id"] for r in dropped}
    state_urls[:] = [u for u in state_urls if u.id not in drop]
    return kept, len(dropped)

def _tab_already_owned(urls, tab_id: str) -> bool:
    """One row per tab (I-33): never add a second."""
    for u in urls:
        if u.tab_id == tab_id:
            return True
    return False

def _add_missing_rows(urls, adds) -> int:
    """Append rows for tabs none owns yet; returns count added."""
    added = 0
    for url, tab_id in adds:
        if _tab_already_owned(urls, tab_id):
            continue
        from app.core.models import UrlRow
        urls.append(UrlRow.create(url, enabled=True, tab_id=tab_id))
        added += 1
    return added

