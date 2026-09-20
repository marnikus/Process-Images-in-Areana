"""URL queue panel — URL rows, URL presets, run-gate helpers.

Owns the I-33 row<->tab helpers (single source; `app.ui.bridge` keeps
compat re-exports used by `tests/test_url_selection.py`) plus the 9 slots.
Imports go panels -> services/core only. Every slot returns a JSON string
(QWebChannel callbacks never fire for `None`), and every row mutation goes
through `commit_urls` (persist + emit + undo) — 2026-10-02 bugfix.
"""

import json
from datetime import datetime

from app.core.models import UrlRow
from app.services.auto_connect import (
    claim_unlinked_from_pool,
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
    from app.services.live.url_policy import dedupe_rows as _dp
    kept, dropped = _dp(state_urls)
    if dropped:
        drop_ids = {getattr(u, "id", "") for u in dropped}
        state_urls[:] = [u for u in state_urls if getattr(u, "id", "") not in drop_ids]
    return kept, len(dropped)


def _tab_already_owned(urls, tab_id: str) -> bool:
    """One row per tab (I-33): never add a second."""
    for u in urls:
        if u.tab_id == tab_id:
            return True
    return False


def _add_missing_rows(urls, adds) -> int:
    from app.services.live.url_policy import add_rows as _ar
    return _ar(urls, adds)


def push_urls_undo(bridge) -> None:
    """Snapshot URL rows to undo (best effort)."""
    try:
        js_urls = arena_serialize.arena_to_js(bridge.state)["urls"]
        bridge.undo_service.push("urls", js_urls)
        undo_entries.emit_undo_state(bridge)
    except Exception:
        pass


MAX_URL_LEN = 2048  # browsers/CDP choke on longer; keeps the arena.json row sane


def _valid_new_url(url: str):
    """Trimmed URL or an error string (add/edit gate)."""
    url = (url or "").strip()
    if not url:
        return None, "empty URL"
    if not (url.startswith("http://") or url.startswith("https://")):
        return None, "URL must start with http:// or https://"
    if len(url) > MAX_URL_LEN:
        return None, f"URL too long (>{MAX_URL_LEN} chars)"
    return url, ""


def _duplicate_url(urls, url: str, skip_id: str = "") -> bool:
    """Same URL already on another row (case-sensitive, trailing-slash exact)."""
    return any(u.url == url and u.id != skip_id for u in urls)


def _recompute_receivers(bridge) -> int:
    try:
        from app.services.live.url_policy import mark_receivers
        from app.services.run_state import pooled_ids
        rows = getattr(bridge.state, "urls", [])
        return int(mark_receivers(rows, enabled_tab_ids(rows), pooled_ids(getattr(bridge, "_page_pool", None))) or 0)
    except Exception:
        return 0


def commit_urls(bridge) -> None:
    """The ONE write path for URL rows: persist + emit state + undo snapshot.

    Bug 2026-10-02: slots that saved without emitting left the table stale
    until the next unrelated refresh; `_save_arena` emits `arena_state_updated`
    and `push_urls_undo` records the global undo entry (RULE 12).
    """
    try:
        _recompute_receivers(bridge)
    except Exception:
        pass
    bridge._save_arena()
    push_urls_undo(bridge)


def _find_url(urls, url_id: str):
    """URL row by id (None when missing)."""
    for u in urls:
        if u.id == url_id:
            return u
    return None


class UrlQueueMixin:
    """URL rows and URL preset slots — every slot returns JSON (never None)."""

    def _commit_urls(self) -> None:
        commit_urls(self)

    @Slot(str, result=str)
    def add_url(self, url: str):
        url, err = _valid_new_url(url)
        if err:
            return json.dumps({"ok": False, "error": err})
        if _duplicate_url(self.state.urls, url):
            return json.dumps({"ok": False, "error": "URL already exists"})
        item = UrlRow.create(url, enabled=True)
        self.state.urls.append(item)
        self._commit_urls()
        return json.dumps({"ok": True, "id": item.id})

    @Slot(str, result=str)
    def remove_url(self, url_id: str):
        before = len(self.state.urls)
        self.state.urls = [u for u in self.state.urls if u.id != url_id]
        if len(self.state.urls) == before:
            return json.dumps({"ok": False, "error": "not found"})
        self._commit_urls()
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def toggle_url(self, url_id: str):
        row = _find_url(self.state.urls, url_id)
        if row is None:
            return json.dumps({"ok": False, "error": "not found"})
        row.enabled = not row.enabled
        self._commit_urls()
        return json.dumps({"ok": True, "enabled": row.enabled})

    @Slot(str, str, result=str)
    def edit_url(self, url_id: str, new_url: str):
        new_url, err = _valid_new_url(new_url)
        if err:
            return json.dumps({"ok": False, "error": err})
        row = _find_url(self.state.urls, url_id)
        if row is None:
            return json.dumps({"ok": False, "error": "not found"})
        if _duplicate_url(self.state.urls, new_url, skip_id=url_id):
            return json.dumps({"ok": False, "error": "URL already exists"})
        row.url = new_url
        row.last_status = "unchecked"
        row.error = None
        self._commit_urls()
        return json.dumps({"ok": True, "url": new_url})

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

    def _emit_url_presets(self) -> str:
        payload = json.dumps(self.config.presets.get_url_presets(), ensure_ascii=False)
        self.url_presets_updated.emit(payload)
        self.presets_changed.emit("urls", payload)
        return payload

    @Slot(str, result=str)
    def add_url_preset(self, url: str):
        url = (url or "").strip()
        if not url:
            self._log("⚠ URL field empty — nothing added", "warn")
            return json.dumps({"ok": False, "error": "empty URL"})
        try:
            added = bool(self.config.presets.add_url_preset(url))
            self._log(f"💾 URL bookmark added: {url}" if added
                      else f"ℹ URL bookmark already exists: {url}", "success" if added else "info")
            return json.dumps({"ok": True, "added": added, "presets": json.loads(self._emit_url_presets())})
        except Exception as e:
            self._log(f"Add bookmark failed: {e}", "error")
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def remove_url_preset(self, url: str):
        try:
            removed = bool(self.config.presets.remove_url_preset(url))
            if removed:
                self._log(f"🗑 URL bookmark removed: {url}", "warn")
            return json.dumps({"ok": True, "removed": removed, "presets": json.loads(self._emit_url_presets())})
        except Exception as e:
            self._log(f"Remove bookmark failed: {e}", "error")
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def set_last_url_preset(self, url: str):
        url = (url or "").strip()
        if not url:
            return json.dumps({"ok": False, "error": "empty URL"})
        self.config.set_state(last_url_preset=url)
        self._log(f"🔖 Bookmark remembered: {url}", "info")
        return json.dumps({"ok": True})
