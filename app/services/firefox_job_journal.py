"""Firefox job journal — the write-ahead checkpoint store (design D-9, 2026-09-25).

One record per in-flight Firefox image job, keyed by the correlation id, in
`config/firefox_jobs.json` (atomic write + shape-validated load through
`persistence.json_store`, RULE 13). The record is the `JobRecord` shape
(`job_id`, `status`, `baseline`, `submitted_at`, `output_src`, `saved_path`,
`error`, `needs_review`, …) plus the Firefox evidence the recovery needs
(`tab_id`, `image_id`, `staged_upload`, `prompt_sha256`, `submit_ack`,
`download_path`, `bytes_sha256`, `target_path`).

Status moves are validated against the ONE table `core/state_machine.JOB_TRANSITIONS`
(design D-10): an illegal move is refused and reported, never written. The
write happens BEFORE the side effect it names — `submitted` is on disk before
the send XClick fires, so a record at `submitted` or later is never sent again.
`AppState.jobs` is deliberately not used: Run / Scan clear it (D-9).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.enums import JobStatus
from app.core.state_machine import validate_job_transition
from app.persistence.json_store import load_json, save_json_atomic

FILE_NAME = "firefox_jobs.json"

# a record in one of these may already have reached the site — never resubmit it
POST_SUBMIT = frozenset({
    JobStatus.SUBMITTED.value, JobStatus.WAITING_GENERATION.value,
    JobStatus.OUTPUT_DETECTED.value, JobStatus.DOWNLOADING.value,
    JobStatus.VALIDATING.value, JobStatus.SAVING.value,
})
TERMINAL = frozenset({JobStatus.COMPLETED.value, JobStatus.FAILED.value})


def utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def is_post_submit(record: Optional[dict]) -> bool:
    """True when the site may have received this job (the no-resubmit rule)."""
    return bool(record) and str(record.get("status")) in POST_SUBMIT


def _coerce(data: Any) -> Dict[str, dict]:
    """Saved doc → {job_id: record}; any wrong shape is dropped (RULE 13)."""
    rows = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        return {}
    return {str(k): {**v, "job_id": str(k)} for k, v in rows.items()
            if isinstance(v, dict) and isinstance(v.get("status"), str)}


class JobJournal:
    """RLock-guarded records + atomic save; memory-only without a path (tests)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._records: Dict[str, dict] = _coerce(load_json(path, {})) if path else {}

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            rec = self._records.get(job_id)
            return dict(rec) if rec else None

    def create(self, job_id: str, **fields) -> dict:
        """A new record at `created` (replaces a stale one with the same id)."""
        with self._lock:
            rec = {"job_id": job_id, "status": JobStatus.CREATED.value,
                   "created_at": utc_stamp(), **fields}
            self._records[job_id] = rec
            self._save()
            return dict(rec)

    def advance(self, job_id: str, status: str, **fields) -> bool:
        """Validated status move + evidence fields, persisted; False = refused."""
        with self._lock:
            rec = self._records.get(job_id)
            if rec is None or not validate_job_transition(rec["status"], status):
                return False
            rec.update(fields, status=status, checkpoint_at=utc_stamp())
            self._save()
            return True

    def update(self, job_id: str, **fields) -> bool:
        """Evidence at the same status (e.g. `submit_ack`), persisted."""
        with self._lock:
            rec = self._records.get(job_id)
            if rec is None:
                return False
            rec.update(fields)
            self._save()
            return True

    def drop(self, job_id: str) -> None:
        with self._lock:
            if self._records.pop(job_id, None) is not None:
                self._save()

    def open_records(self) -> List[dict]:
        """Everything not terminal (in flight, interrupted or awaiting review)."""
        with self._lock:
            return [dict(r) for r in self._records.values() if r["status"] not in TERMINAL]

    def _save(self) -> None:
        if self._path is not None:
            save_json_atomic(self._path, {"jobs": self._records})


def journal_of(bridge) -> JobJournal:
    """The bridge's journal (created on first use; memory-only without a config dir)."""
    journal = getattr(bridge, "_firefox_journal", None)
    if journal is None:
        directory = getattr(getattr(bridge, "config", None), "dir", None)
        ok = isinstance(directory, (str, Path))
        journal = JobJournal(Path(directory) / FILE_NAME if ok else None)
        try:
            bridge._firefox_journal = journal
        except Exception:
            pass
    return journal
