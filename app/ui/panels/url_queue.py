"""URL queue panel — URL rows, URL presets, run-gate helpers.

Owns the I-33 row<->tab helpers (single source; `app.ui.bridge` keeps
compat re-exports used by `tests/test_url_selection.py`) plus the 9 slots.
Imports go panels -> services/core only.
"""

import json
from datetime import datetime

from app.core.models import UrlRow
from app.services.auto_connect import (
    claim_unlinked_from_pool,
    dedupe_linked_rows,
    enabled_tab_ids,
)
from app.ui.qt_compat import Slot
from app.ui.services import arena_serialize, undo_entries


def enabled_urls(urls) -> list:
    """Enabled URL rows (run gate input; run_control imports this)."""
    return [u for u in urls if u.enabled]


def _checked_tabs_ready(bridge) -> set:
    """Rescue-claim checked unlinked rows; tab ids usable for runs."""
    try:
        pool = bridge._page_pool
        pages = pool.status_snapshot().get("pages", []) if pool else []
        if claim_unlinked_from_pool(bridge.state.urls, pages):
            bridge._save_arena()
    except Exception:
        pass
    return enabled_tab_ids(enabled_urls(bridge.state.urls))


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
        urls.append(UrlRow.create(url, enabled=True, tab_id=tab_id))
        added += 1
    return added


def push_urls_undo(bridge) -> None:
    """Snapshot URL rows to undo (best effort)."""
    try:
        js_urls = arena_serialize.arena_to_js(bridge.state)["urls"]
        bridge.undo_service.push("urls", js_urls)
        undo_entries.emit_undo_state(bridge)
    except Exception:
        pass


def _valid_new_url(url: str):
    """Trimmed URL or an error string (add-gate)."""
    url = (url or "").strip()
    if not url:
        return None, "empty URL"
    if not (url.startswith("http://") or url.startswith("https://")):
        return None, "URL must start with http:// or https://"
    return url, ""


def _find_url(urls, url_id: str):
    """URL row by id (None when missing)."""
    for u in urls:
        if u.id == url_id:
            return u
    return None


class UrlQueueMixin:
    """URL rows and URL preset slots."""

    @Slot(str, result=str)
    def add_url(self, url: str):
        url, err = _valid_new_url(url)
        if err:
            return json.dumps({"ok": False, "error": err})
        for u in self.state.urls:
            if u.url == url:
                return json.dumps({"ok": False, "error": "URL already exists"})
        item = UrlRow.create(url, enabled=True)
        self.state.urls.append(item)
        self._save_arena()
        push_urls_undo(self)
        return json.dumps({"ok": True, "id": item.id})

    @Slot(str, result=str)
    def remove_url(self, url_id: str):
        before = len(self.state.urls)
        self.state.urls = [u for u in self.state.urls if u.id != url_id]
        if len(self.state.urls) == before:
            return json.dumps({"ok": False, "error": "not found"})
        self._save_arena()
        push_urls_undo(self)
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def toggle_url(self, url_id: str):
        row = _find_url(self.state.urls, url_id)
        if row is None:
            return json.dumps({"ok": False, "error": "not found"})
        row.enabled = not row.enabled
        self._save_arena()
        push_urls_undo(self)
        return json.dumps({"ok": True, "enabled": row.enabled})

    @Slot(str, str, result=str)
    def edit_url(self, url_id: str, new_url: str):
        new_url = (new_url or "").strip()
        if not new_url:
            return json.dumps({"ok": False, "error": "empty URL"})
        row = _find_url(self.state.urls, url_id)
        if row is None:
            return json.dumps({"ok": False, "error": "not found"})
        row.url = new_url
        row.last_status = "unchecked"
        row.error = None
        self._save_arena()
        push_urls_undo(self)
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def test_url(self, url_id: str):
        row = _find_url(self.state.urls, url_id)
        if row is None:
            return json.dumps({"ok": False, "error": "not found"})
        if row.url.startswith("http"):
            row.last_status = "ready"
            row.last_checked = datetime.utcnow().isoformat() + "Z"
            self._save_arena()
            return json.dumps({"ok": True, "status": "ready"})
        row.last_status = "error"
        row.error = "Invalid URL"
        self._save_arena()
        return json.dumps({"ok": False, "error": "Invalid URL"})

    @Slot(result=str)
    def get_url_presets(self):
        try:
            presets = self.config.presets.get_url_presets()
            return json.dumps(presets, ensure_ascii=False)
        except Exception:
            return "[]"

    @Slot(str)
    def add_url_preset(self, url: str):
        url = (url or "").strip()
        if not url:
            self._log("⚠ URL field empty — nothing added", "warn")
            return
        try:
            if self.config.presets.add_url_preset(url):
                self._log(f"💾 URL bookmark added: {url}", "success")
            else:
                self._log(f"ℹ URL bookmark already exists: {url}", "info")
            payload = json.dumps(self.config.presets.get_url_presets(), ensure_ascii=False)
            self.url_presets_updated.emit(payload)
            self.presets_changed.emit("urls", payload)
        except Exception as e:
            self._log(f"Add bookmark failed: {e}", "error")

    @Slot(str)
    def remove_url_preset(self, url: str):
        try:
            if self.config.presets.remove_url_preset(url):
                self._log(f"🗑 URL bookmark removed: {url}", "warn")
            payload = json.dumps(self.config.presets.get_url_presets(), ensure_ascii=False)
            self.url_presets_updated.emit(payload)
            self.presets_changed.emit("urls", payload)
        except Exception as e:
            self._log(f"Remove bookmark failed: {e}", "error")

    @Slot(str)
    def set_last_url_preset(self, url: str):
        url = (url or "").strip()
        if not url:
            return
        self.config.set_state(last_url_preset=url)
        self._log(f"🔖 Bookmark remembered: {url}", "info")
