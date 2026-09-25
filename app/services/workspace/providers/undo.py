"""undo provider — `config/undo.json` (the ONE global undo timeline, RULE 12).

Restore goes through `UndoStore.set` (the same clamp the live writer uses),
so a restored history can never exceed the cap or carry a bad index. The
timeline is restored whole — per-entry cherry-picking would fork the one
history and is rejected by design.
"""

from __future__ import annotations

from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider


def history_error(doc) -> str | None:
    if not isinstance(doc, dict):
        return "document is not an object"
    history = doc.get("history")
    if not isinstance(history, list):
        return "'history' must be a list"
    if any(not isinstance(entry, dict) or not isinstance(entry.get("kind"), str)
           for entry in history):
        return "history entries must be objects with a 'kind'"
    index = doc.get("index")
    if isinstance(index, bool) or not isinstance(index, int):
        return "'index' must be an int"
    return None


class UndoProvider(StateProvider):
    """Global undo timeline (kinds grid/urls/folder/queue/prompt/settings/…)."""

    domain_id = "undo"
    display_name = "Undo History"
    native_rel_path = "state/undo.json"
    schema_version = "1"
    supported_migrations = ("1",)
    sensitivity = "public"

    def live_paths(self, bridge) -> list:
        return self._one_file(bridge.config.undo.path)

    def capture(self, bridge) -> CaptureResult:
        history, index = bridge.config.undo.get()
        return CaptureResult(ok=True, doc={"history": history, "index": index})

    def validate(self, doc) -> str | None:
        return history_error(doc)

    def plan(self, bridge, doc) -> str:
        return f"{len(doc.get('history', []))} undo entr(y/ies), index {doc.get('index')}"

    def apply(self, bridge, doc) -> ApplyOutcome:
        ok = bridge.config.undo.set(list(doc.get("history", [])), int(doc.get("index", -1)))
        if not ok:
            from app.persistence.workspace.errors import WorkspaceError
            raise WorkspaceError(self.domain_id, "apply",
                                 "undo store refused the write (disk or lock)")
        return ApplyOutcome(ok=True)
