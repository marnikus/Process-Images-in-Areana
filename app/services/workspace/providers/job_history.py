"""job_history provider — `config/job_history.json` (append-only finished-job log).

Apply writes the native doc through the same atomic writer and then
rebuilds the live store from the file (same constructor path as boot), so
the in-memory log and the file never disagree. `next_job_no` keeps its
monotonic promise — a restored log never reuses job numbers (I-61).
"""

from __future__ import annotations

from app.persistence.json_store import load_json, save_json_atomic
from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider
from app.services.job_history import FILE_NAME, JobHistoryStore, _history_file


def history_error(doc) -> str | None:
    if not isinstance(doc, dict):
        return "document is not an object"
    if not isinstance(doc.get("entries", []), list):
        return "'entries' must be a list"
    number = doc.get("next_job_no", 1)
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
        path = _history_file(bridge)
        doc = load_json(path, {}) if path else {}
        return CaptureResult(ok=True, doc=doc)

    def validate(self, doc) -> str | None:
        return history_error(doc)

    def plan(self, bridge, doc) -> str:
        return f"{len(doc.get('entries', []))} history row(s)"

    def apply(self, bridge, doc) -> ApplyOutcome:
        path = _history_file(bridge)
        if path is None:
            from app.persistence.workspace.errors import WorkspaceError
            raise WorkspaceError(self.domain_id, "apply", "no config dir for the history file")
        save_json_atomic(path, {"next_job_no": doc.get("next_job_no", 1),
                                "entries": doc.get("entries", [])})
        bridge._job_history = JobHistoryStore(path)
        return ApplyOutcome(ok=True)
