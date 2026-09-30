"""job_history provider — `config/job_history.json` (append-only finished-job log).

Apply writes the native doc through the same atomic writer and then
rebuilds the live store from the file (same constructor path as boot), so
the in-memory log and the file never disagree. `next_job_no` keeps its
monotonic promise — a restored log never reuses job numbers (I-61).
"""

from __future__ import annotations

from app.persistence.json_store import save_json_atomic
from app.persistence.workspace.errors import WorkspaceError
from app.services.workspace.provider import (ApplyOutcome, CaptureResult, StateProvider,
                                         live_capture, members, object_doc)
from app.services.job_history import JobHistoryStore, _history_file


def history_error(doc) -> str | None:
    if (shape := object_doc(doc)):
        return shape
    if (shape := members(doc, entries=list)):
        return shape
    return _next_job_error(doc.get("next_job_no", 1))


def _next_job_error(number) -> str | None:
    """`next_job_no` keeps the monotonic promise (I-61) — never a bool, never < 1."""
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        return "'next_job_no' must be a positive int"
    return None


class JobHistoryProvider(StateProvider):
    """One append-only row per finished job (display history, never the queue — RULE 14)."""

    domain_id = "job_history"
    display_name = "Job History"
    native_rel_path = "state/job_history.json"
    schema_version = "1"
    sensitivity = "personal"   # rows carry local file paths

    def live_paths(self, bridge) -> list:
        return self._one_file(_history_file(bridge))

    def capture(self, bridge) -> CaptureResult:
        return live_capture(_history_file(bridge))

    def validate(self, doc) -> str | None:
        return history_error(doc)

    def apply(self, bridge, doc) -> ApplyOutcome:
        path = _history_file(bridge)
        if path is None:
            raise WorkspaceError(self.domain_id, "apply", "no config dir for the history file")
        save_json_atomic(path, {"next_job_no": doc.get("next_job_no", 1),
                                "entries": doc.get("entries", [])})
        bridge._job_history = JobHistoryStore(path)
        return ApplyOutcome(ok=True)
