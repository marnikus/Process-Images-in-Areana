"""Firefox job crash recovery — reconcile the journal before any retry (design §16, 2026-09-25).

Runs once when the live loop starts, BEFORE `recover_stale_processing` turns
`processing` leftovers back into `pending`. For every open journal record:

* saved file already beside the source (same SHA-256) → image completed
  (the state write was interrupted — never re-generate);
* bytes staged in the job folder → validate + atomic `_AI` save → completed;
* correlated `output_src` known → fetch + validate + save → completed
  (generated but not downloaded — collected without a resubmit);
* anything else after the submit → needs_review (the message may be on the
  site; the user decides — never resubmitted automatically);
* before the submit → failed record dropped, the image is re-queued as usual.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.core.enums import ImageStatus, JobStatus
from app.services import firefox_job_output as out
from app.services.firefox_job_ctx import JOBS_DIR, config_dir
from app.services.firefox_job_journal import is_post_submit, journal_of
from app.services.firefox_job_upload import drop_staged

REVIEW_MSG = "interrupted after submit — result not collected; check the Firefox tab"


def _image_of(bridge, record: dict):
    image_id, path = record.get("image_id"), record.get("image_path")
    for img in getattr(bridge.state, "images", []) or []:
        if (image_id and getattr(img, "id", None) == image_id) or str(img.absolute_path) == path:
            return img
    return None


def _save_bytes(bridge, source, data: bytes) -> Path:
    ext = out.validate_image(data)
    return out.save_beside(source, data, out.output_spec(bridge.state.settings, ext))


def _salvage(bridge, record: dict, source) -> Optional[Path]:
    """The saved / re-saved / fetched result, or None (never generates anything)."""
    sha = record.get("bytes_sha256") or ""
    if sha:
        found = out.find_saved(source, sha, _suffix(bridge))
        if found:
            return found
        data = out.read_staged(record.get("download_path"), sha)
        if data:
            return _save_bytes(bridge, source, data)
    src = record.get("output_src") or ""
    if src.startswith("http"):
        return _save_bytes(bridge, source, out.fetch(src, 60))
    return None


def _suffix(bridge) -> str:
    try:
        return bridge.state.settings.output.get("suffix", "_AI")
    except Exception:
        return "_AI"


def _log(bridge, message: str, level: str = "info") -> None:
    try:
        bridge._log(message, level)
    except Exception:
        pass


@dataclass
class _Case:
    """One open record under recovery (RULE 16 parameter budget)."""

    bridge: Any
    journal: Any
    record: dict
    img: Any

    @property
    def job_id(self) -> str:
        return self.record["job_id"]


def _complete(case: _Case, path: Path) -> str:
    case.img.status, case.img.error, case.img.output_path = ImageStatus.COMPLETED.value, None, str(path)
    case.journal.drop(case.job_id)
    shutil.rmtree(config_dir(case.bridge) / JOBS_DIR / case.job_id, ignore_errors=True)
    _log(case.bridge, f"♻ 🦊 [{case.job_id}] recovered — {path.name} saved, no resubmit", "success")
    return "completed"


def _review(case: _Case, reason: str) -> str:
    message = f"{REVIEW_MSG} ({reason})" if reason else REVIEW_MSG
    case.journal.advance(case.job_id, JobStatus.NEEDS_REVIEW.value, error=message, needs_review=True)
    if case.img is not None:
        case.img.status, case.img.error = ImageStatus.NEEDS_REVIEW.value, message
    _log(case.bridge, f"⚠ 🦊 [{case.job_id}] needs review — {message}", "warn")
    return "needs_review"


def _before_submit(record: dict) -> bool:
    return not is_post_submit(record) and record.get("status") != JobStatus.NEEDS_REVIEW.value


async def recover_one(bridge, journal, record: dict) -> str:
    """One record → 'completed' | 'needs_review' | 'dropped'."""
    drop_staged(record.get("staged_upload"))
    case = _Case(bridge, journal, record, _image_of(bridge, record))
    if _before_submit(record):
        journal.advance(case.job_id, JobStatus.FAILED.value, error="interrupted before submit")
        journal.drop(case.job_id)
        return "dropped"
    try:
        path = await asyncio.to_thread(_salvage, bridge, record, case.img.absolute_path) if case.img else None
    except (out.OutputError, OSError) as exc:
        return _review(case, str(exc))
    if path is not None:
        return _complete(case, path)
    if record.get("status") == JobStatus.NEEDS_REVIEW.value:
        return "needs_review"
    return _review(case, "")


async def recover_firefox_jobs(bridge) -> dict:
    """Reconcile every open record; {outcome: count} (saved once if anything changed)."""
    journal = journal_of(bridge)
    counts: dict = {}
    for record in journal.open_records():
        try:
            outcome = await recover_one(bridge, journal, record)
        except Exception as exc:  # recovery must never stop the live loop (RULE 4: say it)
            _log(bridge, f"⚠ 🦊 [{record.get('job_id')}] recovery failed: {exc}", "warn")
            outcome = "error"
        counts[outcome] = counts.get(outcome, 0) + 1
    if counts:
        try:
            bridge.state.recalculate_progress()
            bridge._save_arena()
        except Exception:
            pass
    return counts
