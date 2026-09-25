"""Pure decisions for one Firefox image job (I-65).

No browser, no disk writes. Empty and broken stay different answers (RULE 4).
A checkpoint restore rewrites the live book — a later edit does not merge in.

Imports: stdlib + core naming (sibling-layer via services → core).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.naming import AI_SUFFIX, parse_ai_output

SOURCE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
PARTIAL_SUFFIXES = (".part", ".crdownload", ".tmp", ".download", ".partial")
SAVED_PHASES = frozenset({"saving", "saved"})


@dataclass
class Corr:
    """One correlation answer. `kind` is ok | rejected | review | pending."""

    kind: str
    reason: str
    src: str = ""


def source_problem(path: str) -> str:
    """'' when the source can be uploaded; a named miss otherwise (RULE 4)."""
    file = Path(path or "")
    if not file.is_file():
        return "missing source file"
    if file.suffix.lower() not in SOURCE_EXTS:
        return "unsupported source file"
    try:
        size = file.stat().st_size
    except OSError as exc:
        return f"source unreadable: {exc}"
    if size <= 0:
        return "empty source file"
    return ""


def _owns(candidate: dict, corr_id: str) -> bool:
    """True when the candidate text or job id is this job's token (RULE 22)."""
    if not corr_id:
        return False
    if str(candidate.get("job_id") or "") == corr_id:
        return True
    return corr_id in str(candidate.get("text") or "")


def _fresh(candidates, baseline) -> list:
    known = set(baseline or ())
    return [c for c in candidates or () if c.get("src") and c["src"] not in known]


def correlate(baseline, candidates, corr_id: str) -> Corr:
    """New result belonging to this job, or a named rejection / review."""
    fresh = _fresh(candidates, baseline)
    matched = [c for c in fresh if _owns(c, corr_id)]
    if len(matched) == 1:
        return Corr("ok", "correlated", matched[0]["src"])
    if len(matched) > 1 or len(fresh) > 1:
        return Corr("review", "multiple result candidates")
    if fresh:
        return Corr("rejected", "result rejected — not the current job")
    if candidates:
        return Corr("rejected", "old result rejected by baseline")
    return Corr("pending", "no candidate")


def attachment_problem(preview: dict, expected: str) -> str:
    """'' when the preview is the file we just attached."""
    if not preview or not preview.get("found"):
        return "missing attachment preview"
    name = str(preview.get("name") or preview.get("alt") or "")
    if expected and expected not in name and not preview.get("fresh"):
        return "wrong attachment preview"
    return ""


def stale_attachment(preview: dict, expected: str) -> bool:
    """A preview from an earlier job is still on the composer."""
    if not preview or not preview.get("found"):
        return False
    name = str(preview.get("name") or preview.get("alt") or "")
    return bool(expected) and expected not in name


def prompt_problem(actual: str, expected: str) -> str:
    """'' on exact read-back; truncated and duplicated are named (RULE 4)."""
    if actual == expected:
        return ""
    if expected and actual.count(expected) > 1:
        return "duplicated prompt readback"
    if actual and expected.startswith(actual) and len(actual) < len(expected):
        return "truncated prompt readback"
    return "prompt readback mismatch"


def download_problem(offer: dict) -> str:
    """'' when a finished file started; partial and missing are named."""
    if not offer or not offer.get("started"):
        return "download does not start"
    if str(offer.get("error") or "") == "html":
        return "Downloaded file is HTML, not image"
    name = str(offer.get("name") or "")
    if offer.get("partial") or name.endswith(PARTIAL_SUFFIXES):
        return "temporary/partial download"
    return ""


def claim_block(page, allowed) -> str:
    """Why this worker must not be given a job; '' when it may."""
    if page is None:
        return "removed"
    tab = getattr(page, "tab_id", "") or ""
    if allowed is not None and tab not in allowed:
        return "disabled"
    if getattr(page, "is_busy", lambda: False)():
        return "busy"
    cooling = getattr(page, "is_cooling", lambda: False)()
    if cooling or str(getattr(page, "status", "")) == "cooldown":
        return "cooling"
    return ""


def sibling_output(source: str):
    """The `_AI` file beside `source`, if one exists (never a different base)."""
    file = Path(source or "")
    if not file.name:
        return None
    for candidate in file.parent.glob(f"{file.stem}{AI_SUFFIX}*{file.suffix}"):
        parsed = parse_ai_output(candidate.stem)
        if parsed and parsed[0] == file.stem and candidate.is_file():
            return candidate
    return None


def should_reconcile(status: str, phase: str, stamp: bool, sibling) -> bool:
    """Interrupted save only. A pending image is a regenerate, even if a sibling exists."""
    if sibling is None or status == "pending":
        return False
    return bool(stamp or phase in SAVED_PHASES)


def restore_book(saved: dict) -> dict:
    """Restore rewrites the live book. A later edit's fields do not survive."""
    return dict(saved or {})


def control_kind(cancel: bool, submitted: bool) -> str:
    """cancel_before | cancel_after | run. Stop-after is not a cancel."""
    if not cancel:
        return "run"
    return "cancel_after" if submitted else "cancel_before"
