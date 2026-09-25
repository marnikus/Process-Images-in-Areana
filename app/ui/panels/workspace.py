# ideal-size: 6 frozen JS slots; save/preview/restore bodies delegate to the
# services coordinator (module funcs) — splitting would scatter slot<->helper
# pairs that always change together (RULE 18.2)
"""Workspace panel — the "Global Saving System" window (19th window, I-51).

Slots only (thin); folder/manifest/report logic lives in
`app/services/workspace/` (coordinator/save/restore — no Qt). The window
keeps every existing feature Save/Preset control untouched (task rule 2):
it is an orchestrator over the native stores, nothing else.
"""

import json

from app.services import job_history
from app.services.workspace import apply as ws_apply
from app.services.workspace import restore as ws_restore
from app.services.workspace import save as ws_save
from app.services.workspace.coordinator import SaveRequest, default_base
from app.ui.qt_compat import QFileDialog, Slot
from app.ui.services import file_service, undo_entries


def _options(raw: str) -> dict:
    """Parsed options object ({} on any garbage — the slot never raises)."""
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _state_payload(bridge) -> dict:
    return {
        "default_dir": str(default_base(bridge)),
        "recent": ws_save.recent_snapshots(bridge),
        "last_snapshot": ws_save.last_snapshot(bridge),
        "last_restore": ws_save.last_restore(bridge),
    }


def _do_save(bridge, opts: dict) -> dict:
    request = SaveRequest(
        name=str(opts.get("name") or "workspace"),
        description=str(opts.get("description") or ""),
        selected=opts.get("selected"),
        allow_partial=bool(opts.get("allow_partial")),
        base_dir=str(opts.get("base_dir") or ""),
    )
    return ws_save.save_workspace(bridge, request)


def _do_restore(bridge, root: str, opts: dict) -> dict:
    return ws_apply.restore_workspace(bridge, root, selected=opts.get("selected"))


def _emit_refresh(bridge, emit, note: str, notes: list) -> None:
    """One best-effort live push; a missing signal/logs on test fakes is a note."""
    try:
        emit()
        notes.append(note)
    except Exception as exc:
        notes.append(f"{note} failed: {type(exc).__name__}: {exc}")


def _post_restore_refresh(bridge, restored: list) -> list:
    """Push restored state to every LIVE consumer (panels + signals).

    Files and stores alone leave the UI showing pre-restore values — and the
    next Settings save would clobber the restore back (2026-09-25 owner bug
    report: "restore do nothing"). Each push reuses the app's own emitter.
    """
    notes: list = []
    if "arena_state" in restored:
        _emit_refresh(bridge, lambda: bridge._emit_arena_state(),
                      "live state re-pushed (queue, urls, settings inputs)", notes)
    if "undo" in restored:
        _emit_refresh(bridge, lambda: undo_entries.emit_undo_state(bridge),
                      "undo timeline re-pushed", notes)
    if "job_history" in restored:
        _emit_refresh(bridge, lambda: job_history.emit_history(bridge),
                      "job history re-pushed", notes)
    if "window_presets" in restored:
        _emit_refresh(bridge, lambda: bridge.list_window_presets(),
                      "window preset list re-pushed", notes)
    if "arena_presets" in restored:
        _emit_refresh(bridge, lambda: bridge.list_arena_presets(),
                      "arena preset list re-pushed", notes)
    return notes


def _dialog_folder(mode: str) -> dict:
    """OS folder picker; headless falls back to an explicit error (RULE 4)."""
    if QFileDialog is None:
        return {"ok": False, "error": "No folder dialog in headless mode"}
    title = ("Choose where to save the workspace"
             if mode == "save-base" else "Choose a workspace snapshot folder")
    chosen = QFileDialog.getExistingDirectory(None, title)
    if not chosen:
        return {"ok": False, "cancelled": True}
    return {"ok": True, "path": chosen}


def clamp_restored_geometry(bridge) -> str:
    """Clamp a restored window geometry onto the current screen (grid W6 rule).

    Qt lives here (panel layer); the provider stays Qt-free. Best effort —
    a missing screen service keeps the restored numbers.
    """
    geometry = bridge.config.get_state("window_geometry", None)
    if not isinstance(geometry, dict):
        return ""
    try:
        from app.ui.qt_compat import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        width = min(int(geometry.get("width", 0)), screen.width())
        height = min(int(geometry.get("height", 0)), screen.height())
        x = max(screen.left(), min(int(geometry.get("x", 0)), screen.right() - 100))
        y = max(screen.top(), min(int(geometry.get("y", 0)), screen.bottom() - 100))
        clamped = {"x": x, "y": y, "width": width, "height": height}
        if clamped != geometry:
            bridge.config.set_state(window_geometry=clamped)
            return "window geometry clamped to this screen"
    except Exception:
        pass
    return ""


class WorkspaceMixin:
    """Global Saving System slots: save / preview / restore / browse / reveal."""

    @Slot(result=str)
    def get_workspace_state(self):
        return json.dumps(_state_payload(self), ensure_ascii=False)

    @Slot(str, result=str)
    def save_workspace(self, options_json: str):
        result = _do_save(self, _options(options_json))
        return json.dumps(result, ensure_ascii=False)

    @Slot(str, result=str)
    def preview_workspace(self, root: str):
        return json.dumps(ws_restore.preview_restore(root), ensure_ascii=False)

    @Slot(str, str, result=str)
    def restore_workspace(self, root: str, options_json: str):
        result = _do_restore(self, root, _options(options_json))
        if result.get("ok"):
            if "grid_window" in (result.get("restored") or []):
                note = clamp_restored_geometry(self)
                if note:
                    result.setdefault("reconciled", []).append(note)
            result.setdefault("reconciled", []).extend(
                _post_restore_refresh(self, result.get("restored") or []))
        return json.dumps(result, ensure_ascii=False)

    @Slot(str, result=str)
    def browse_workspace_folder(self, mode: str):
        return json.dumps(_dialog_folder(mode), ensure_ascii=False)

    @Slot(str, result=bool)
    def open_workspace_path(self, path: str):
        """Reveal a snapshot folder (or its report) in the OS file manager."""
        outcome = file_service.reveal_path(path, log=lambda m, l="info": self._log(m, l))
        if not outcome.get("ok", False):
            self._log(f"Could not open: {outcome.get('error', path)}", "warn")
        return bool(outcome.get("ok"))
