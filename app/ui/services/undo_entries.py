# ideal-size: ~400 lines reason=three kind-dispatch tables (remember/apply/empty) share one kind vocabulary plus row builders; splitting would scatter remember/apply twins that always change together (RULE 18.2)
"""Undo entry remember/apply — kind dispatch (no Qt/signals/panels).

Owns the per-kind state mutations for global undo plus the undo-step flow.
Panels call these with the bridge duck-type; shared row builders keep the
remember/apply twins identical. A dead duplicate `action_blocks` branch in
the legacy apply chain was deleted (unreachable, RULE 16.2 allows).
"""

from __future__ import annotations

import json
import logging

from app.core.layout_service import canonical_grid_payload, default_payload
from app.core.models import UrlRow

log = logging.getLogger("arena")


def url_rows_from_js(value: list) -> list:
    """JS url dicts -> UrlRow list (id fallback + last-checked + tab link kept)."""
    return [UrlRow(
        id=u.get("id", f"url_{i}"),
        url=u.get("url", ""),
        enabled=u.get("enabled", True),
        last_status=u.get("status", "unchecked"),
        last_checked=u.get("last_checked"),
        error=u.get("last_error") or u.get("error"),
        tab_id=u.get("tab_id") or "",  # B7: undo/redo used to unlink every tab
        receiver=bool(u.get("receiver", False)),
        typed=bool(u.get("typed", False)),  # I-64: undo keeps a typed row protected
    ) for i, u in enumerate(value)]


def arena_url_rows_from_js(urls: list) -> list:
    """Arena-snapshot url dicts -> UrlRow list (strict ids, tab link kept)."""
    return [UrlRow(
        id=u.get("id"), url=u.get("url"), enabled=u.get("enabled", True),
        last_status=u.get("status", "unchecked"), error=u.get("last_error"),
        tab_id=u.get("tab_id") or "", receiver=bool(u.get("receiver", False)),
        typed=bool(u.get("typed", False)),
    ) for u in urls]


def emit_undo_state(bridge) -> None:
    """Emit history/index/canUndo/canRedo payloads."""
    try:
        hist, idx = bridge.undo_service.history()
        payload = json.dumps({
            "history": hist,
            "index": idx,
            "canUndo": idx >= 0,
            "canRedo": idx < len(hist) - 1,
            "count": len(hist),
        }, ensure_ascii=False)
        bridge.undo_state_changed.emit(payload)
        bridge.history_changed.emit()
    except Exception as e:
        log.warning(f"emit undo state failed: {e}")


def coerce_push_value(kind: str, value):
    """Validate a pushed value (grid must canonicalize); returns (value, ok)."""
    if kind != "grid":
        return value, True
    payload, err = canonical_grid_payload(
        value if isinstance(value, str) else json.dumps(value))
    if err:
        return value, False
    return payload, True


# ---- remember (apply a pushed edit immediately) ----

def _remember_grid(bridge, value) -> None:
    bridge.config.set_state(grid_layout=value)
    bridge.grid_layout_changed.emit(value)
    bridge.grid_layout_persisted.emit(True)


def _remember_window_states(bridge, value) -> None:
    if isinstance(value, dict):
        bridge.config.set_state(window_states=value)


def _remember_urls(bridge, value) -> None:
    if isinstance(value, list):
        bridge.state.urls = url_rows_from_js(value)
        bridge._save_arena()


def _remember_folder(bridge, value) -> None:
    if isinstance(value, dict):
        bridge.state.folder.update(value)
        bridge._save_arena()


def _remember_queue(bridge, value) -> None:
    if not isinstance(value, list):
        return
    sel_map = {img.get("id"): img.get("selected") for img in value}
    for im in bridge.state.images:
        if im.id in sel_map:
            im.selected = bool(sel_map[im.id])
    bridge.state.recalculate_progress()
    bridge._save_arena()


def _remember_prompt(bridge, value) -> None:
    if isinstance(value, str):
        bridge.state.prompt["user_prompt"] = value
        bridge._save_arena()
    elif isinstance(value, dict):
        tmpl = value.get("template") or value.get("user_prompt") or ""
        bridge.state.prompt["user_prompt"] = tmpl
        bridge._save_arena()


def _remember_settings(bridge, value) -> None:
    if not isinstance(value, dict):
        return
    bridge.state.settings.timeouts.update(value.get("timeouts", {}))
    bridge.state.settings.output.update(value.get("output", {}))
    bridge.state.settings.highlight.update(value.get("highlight", {}))
    if "supported_types" in value:
        bridge.state.folder["supported_types"] = value["supported_types"]
    bridge._save_arena()


def _remember_action_blocks(bridge, value) -> None:
    if not isinstance(value, list):
        return
    try:
        bridge.config.set_state(action_blocks=value)
        bridge.action_blocks_updated.emit(json.dumps(value, ensure_ascii=False))
        bridge._log(f"↩ Remember action_blocks ({len(value)} blocks)", "info")
    except Exception as e:
        log.warning(f"remember action_blocks failed: {e}")


def _remember_arena_urls(bridge, value) -> None:
    """Snapshot urls in JS shape -> rows (guarded, never partial-applies)."""
    urls = value.get("urls", [])
    if not urls or not isinstance(urls, list) or "url" not in urls[0]:
        return
    bridge.state.urls = arena_url_rows_from_js(urls)


def _remember_arena_rest(bridge, value) -> None:
    """Snapshot folder + prompt halves."""
    if "folder" in value:
        bridge.state.folder.update(value["folder"])
    if "prompt" in value:
        tmpl = value["prompt"].get("template") if isinstance(value["prompt"], dict) else value["prompt"]
        if tmpl:
            bridge.state.prompt["user_prompt"] = tmpl


def _remember_arena(bridge, value) -> None:
    if not isinstance(value, dict):
        return
    try:
        _remember_arena_urls(bridge, value)
        _remember_arena_rest(bridge, value)
        bridge.state.recalculate_progress()
        bridge._save_arena()
    except Exception as e:
        log.warning(f"remember arena edit failed: {e}")


REMEMBER = {
    "grid": _remember_grid,
    "window_states": _remember_window_states,
    "urls": _remember_urls,
    "folder": _remember_folder,
    "queue": _remember_queue,
    "prompt": _remember_prompt,
    "settings": _remember_settings,
    "action_blocks": _remember_action_blocks,
    "arena": _remember_arena,
}


def remember_global_edit(bridge, kind: str, value) -> None:
    """Apply a pushed edit to live state (unknown kinds ignored)."""
    try:
        handler = REMEMBER.get(kind)
        if handler:
            handler(bridge, value)
    except Exception as e:
        log.warning(f"_remember_global_edit {kind} failed: {e}")


# ---- apply (restore an entry on undo/redo) ----

def _apply_grid(bridge, value) -> None:
    if isinstance(value, str):
        bridge.config.set_state(grid_layout=value)
        bridge.grid_layout_changed.emit(value)
        bridge.grid_layout_persisted.emit(True)
        bridge._log("↩ Undo grid layout", "info")


def _apply_window_states(bridge, value) -> None:
    if isinstance(value, dict):
        bridge.config.set_state(window_states=value)
        bridge._log("↩ Undo window states", "info")


def _apply_urls(bridge, value) -> None:
    if isinstance(value, list):
        bridge.state.urls = url_rows_from_js(value)
        bridge._save_arena()
        bridge._log(f"↩ Undo URLs ({len(value)} items)", "info")


def _apply_folder(bridge, value) -> None:
    if isinstance(value, dict):
        bridge.state.folder = value
        bridge._save_arena()
        bridge._log("↩ Undo folder", "info")


def _apply_queue(bridge, value) -> None:
    if not isinstance(value, list):
        return
    sel_map = {img.get("id"): img for img in value}
    for im in bridge.state.images:
        if im.id in sel_map:
            js = sel_map[im.id]
            im.selected = bool(js.get("selected", im.selected))
            im.status = js.get("status", im.status)
    bridge.state.recalculate_progress()
    bridge._save_arena()
    bridge._log("↩ Undo queue selection", "info")


def _apply_prompt(bridge, value) -> None:
    if isinstance(value, str):
        tmpl = value
    elif isinstance(value, dict):
        tmpl = value.get("template")
    else:
        tmpl = ""
    bridge.state.prompt["user_prompt"] = tmpl
    bridge._save_arena()
    bridge._log("↩ Undo prompt", "info")


def _apply_settings(bridge, value) -> None:
    if not isinstance(value, dict):
        return
    if "timeouts" in value:
        bridge.state.settings.timeouts.update(value["timeouts"])
    if "output" in value:
        bridge.state.settings.output.update(value["output"])
    if "highlight" in value:
        bridge.state.settings.highlight.update(value["highlight"])
    if "supported_types" in value:
        bridge.state.folder["supported_types"] = value["supported_types"]
        bridge.state.settings.supported_types = value["supported_types"]
    bridge._save_arena()
    bridge._log("↩ Undo settings", "info")


def _apply_action_blocks(bridge, value) -> None:
    if not isinstance(value, list):
        return
    try:
        bridge.config.set_state(action_blocks=value)
        bridge.action_blocks_updated.emit(json.dumps(value, ensure_ascii=False))
        bridge._log(f"↩ Remember action_blocks ({len(value)} blocks)", "info")
    except Exception as e:
        log.warning(f"remember action_blocks failed: {e}")


def _apply_arena(bridge, value) -> None:
    if not isinstance(value, dict):
        return
    try:
        if "urls" in value:
            bridge.state.urls = arena_url_rows_from_js(value["urls"])
        if "folder" in value:
            bridge.state.folder.update(value["folder"])
        if "prompt" in value:
            prompt = value["prompt"]
            tmpl = prompt.get("template") if isinstance(prompt, dict) else str(prompt)
            bridge.state.prompt["user_prompt"] = tmpl
        bridge.state.recalculate_progress()
        bridge._save_arena()
        bridge._log("↩ Undo arena snapshot", "info")
    except Exception as e:
        log.warning(f"apply arena undo failed: {e}")


APPLY = {
    "grid": _apply_grid,
    "window_states": _apply_window_states,
    "urls": _apply_urls,
    "folder": _apply_folder,
    "queue": _apply_queue,
    "prompt": _apply_prompt,
    "settings": _apply_settings,
    "action_blocks": _apply_action_blocks,
    "arena": _apply_arena,
}


def apply_undo_entry(bridge, entry) -> bool:
    """Restore one history entry; unknown kinds log and succeed."""
    if not entry or not isinstance(entry, dict):
        return False
    kind = entry.get("kind")
    value = entry.get("value")
    try:
        handler = APPLY.get(kind)
        if handler is None:
            bridge._log(f"↩ Undo {kind} (no specific handler)", "info")
        else:
            handler(bridge, value)
        return True
    except Exception as e:
        log.warning(f"_apply_undo_entry {kind} failed: {e}")
        return False


# ---- undo-to-empty (undo past the first entry) ----

def _empty_folder() -> dict:
    return {"root_path": "", "supported_types": [".png", ".jpg", ".jpeg", ".webp"],
            "ignore_ai_suffix": True}


def _empty_grid(bridge) -> None:
    payload = default_payload()
    bridge.config.set_state(grid_layout=payload)
    bridge.grid_layout_changed.emit(payload)
    bridge.grid_layout_persisted.emit(True)
    bridge._log("↩ Undo grid → default", "info")


def _empty_window_states(bridge) -> None:
    bridge.config.set_state(window_states={"closed": [], "minimized": []})
    bridge._log("↩ Undo window states → empty", "info")


def _empty_urls(bridge) -> None:
    bridge.state.urls = []
    bridge._save_arena()
    bridge._log("↩ Undo urls → empty", "info")


def _empty_folder_state(bridge) -> None:
    bridge.state.folder = _empty_folder()
    bridge._save_arena()
    bridge._log("↩ Undo folder → empty", "info")


def _empty_prompt(bridge) -> None:
    bridge.state.prompt["user_prompt"] = ""
    bridge._save_arena()
    bridge._log("↩ Undo prompt → empty", "info")


EMPTY = {
    "grid": _empty_grid,
    "window_states": _empty_window_states,
    "urls": _empty_urls,
    "folder": _empty_folder_state,
    "prompt": _empty_prompt,
}


def undo_to_empty(bridge, kind) -> None:
    """Restore the default/empty state for an undone-past-start kind."""
    try:
        handler = EMPTY.get(kind)
        if handler:
            handler(bridge)
        else:
            bridge._log(f"↩ Undo {kind} → empty", "info")
    except Exception as e:
        log.warning(f"undo empty handling failed: {e}")


def _undone_kind(result: dict):
    """Kind of the entry just undone (undone wrapper or flat)."""
    undone = result.get("undone") or result
    if isinstance(undone, dict) and undone.get("kind"):
        return undone.get("kind")
    return result.get("kind")


def undo_step(bridge) -> str:
    """One undo: step back and restore, or empty-state when past start."""
    result = bridge.undo_service.undo()
    if not result:
        bridge._log("⚠ Nothing to undo", "warn")
        emit_undo_state(bridge)
        return "null"
    hist, idx = bridge.undo_service.history()
    if idx == -1:
        undo_to_empty(bridge, _undone_kind(result))
    else:
        current = hist[idx] if 0 <= idx < len(hist) else None
        apply_undo_entry(bridge, current if current else result)
    emit_undo_state(bridge)
    return json.dumps(result, ensure_ascii=False)
