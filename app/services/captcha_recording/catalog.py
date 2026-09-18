"""UI-facing catalog over one recording store: list, label, compare, remove.

Separated from the lifecycle manager (RULE 18): these operations are synchronous
filesystem/read-model work, while the manager owns async recorders and their
per-tab slots. Deletion stays one persistent undo operation; active recorders
are never staged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .comparison import RecordingComparison
from .deletion import RecordingDeletionUndo
from .reader import EvidenceReader
from .store import RecordingStore


class RecordingCatalog:
    """Everything the Recordings window may ask about retained sessions."""

    def __init__(self, store: RecordingStore,
                 active_ids: Optional[Callable[[], Iterable[str]]] = None):
        self.store = store
        self.reader = EvidenceReader(store.root)
        self.comparison = RecordingComparison()
        self.deletion = RecordingDeletionUndo(store.root)
        self._active_ids = active_ids or (lambda: ())

    def list_sessions(self, limit: int | None = 200) -> list[dict[str, Any]]:
        return self.store.list_sessions(limit)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.reader.details(session_id)

    def session_folder(self, session_id: str) -> str:
        return str(self.reader.folder(session_id))

    def compare_sessions(self, left_id: str, right_id: str) -> dict[str, Any]:
        left, right = self.reader.details(left_id), self.reader.details(right_id)
        return self.comparison.compare(left, right)

    def set_labels(self, session_id: str, actor: str, result: str) -> dict[str, Any]:
        return self.store.set_labels(session_id, actor, result)

    def delete_session(self, session_id: str) -> str:
        if session_id in self._active():
            raise RuntimeError("active recording cannot be removed")
        self.deletion.stage([session_id])
        return session_id

    def delete_all_sessions(self) -> dict[str, int]:
        active = self._active()
        session_ids = [row["session_id"] for row in self.store.list_sessions(None)]
        removable = [session_id for session_id in session_ids if session_id not in active]
        deleted = self.deletion.stage(removable)
        return {"deleted": deleted, "skipped_active": len(session_ids) - deleted}

    def undo_delete(self) -> int:
        return self.deletion.undo()

    def _active(self) -> set[str]:
        try:
            return {str(value) for value in self._active_ids()}
        except Exception:
            return set()


def session_folder(root: Path, session_id: str) -> str:
    """Confinement-checked folder path for one session (used by the adapter)."""
    if not session_id or Path(session_id).name != session_id:
        raise ValueError("invalid session id")
    return str(Path(root) / session_id)
