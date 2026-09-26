"""Firefox image job — submit once, correlate, collect (design §6.3–§6.5, 2026-09-25).

Submit: `submitted` is journalled BEFORE the send XClick (write-ahead); the
macro's in-page guard refuses when the prompt / attachment is not ours or the
JOB-ID bubble already exists. Nothing in this lane ever clicks send twice: a
lost acknowledgement makes the job `uncertain`, which the observe loop settles
from page evidence (bubble seen → sent; composer still holding our prompt →
proven NOT sent → safe failure; neither → needs_review).

Wait: Chrome's strict JOB-ID correlation (`build_check_js`) inside a bounded
observe window per macro, the same src ready twice 3 s apart; a result that
never arrives in `timeouts.generation` → needs_review (the delayed result is
collected by the recovery, never resubmitted).

Collect: fetch + gate + PIL, bytes staged in the job folder, atomic `_AI` save
beside the source. A failure after the result exists is needs_review.
"""

from __future__ import annotations

import asyncio
import time

from app.browser.output_state import extract_src, is_job_id_match
from app.browser.uivision import job_macros as uv_job
from app.browser.uivision import job_scripts as js
from app.core.enums import JobStatus
from app.services import firefox_job_output as out
from app.services.firefox_job_ctx import (
    FfJob, JobCancelled, JobFailure, cancel_requested, emit, in_scope, job_dir, log, mark_pool, run_macro, settings_of, timeout_s,
)
from app.services.firefox_job_phases import advance, wait_security
from app.utils.page_errors import match_page_error

ACK_WAIT_MS = 6000
OBSERVE_WINDOW_MS = 12000
UNCERTAIN_POLLS = 2
MISSES_ALLOWED = 3
FETCH_TRIES = 3
FETCH_SETTLE_S = 3  # Chrome sleeps 3 s before its download too


async def phase_submit(job: FfJob) -> None:
    """SUBMIT: journal first, then the guarded single XClick; ack or `uncertain`."""
    emit(job, "SUBMIT", "running", "submit intent (journalled before the click)")
    advance(job, JobStatus.SUBMITTED.value, submitted_at=time.time(), submit_ack=False)
    phase = uv_job.submit_macro(job.corr, js.guard_js(job.corr, job.prompt_sha, job.staged_name),
                                js.ack_js(job.corr, ACK_WAIT_MS))
    replies = await run_macro(job, phase, required=False)
    guard, ack = replies.get("guard") or {}, replies.get("submit") or {}
    refusal = _guard_refusal(guard)
    if refusal:
        raise JobFailure(refusal)
    how = _ack_how(guard, ack)
    if how:
        job.journal.update(job.corr, submit_ack=True)
        emit(job, "SUBMIT", "success", f"submitted (ack: {how})")
        return
    job.uncertain = True
    emit(job, "SUBMIT", "running", "submit uncertain — no acknowledgement; observing, never resubmitting")


def _guard_refusal(guard: dict) -> str:
    """The guard's named refusal ('' = it let the click through or already saw our bubble)."""
    if not guard or guard.get("go") or guard.get("bubble"):
        return ""
    return (f"submit guard refused — not sent (prompt ok={guard.get('promptOk')}, "
            f"attachment ok={guard.get('attachmentOk')}, send enabled={guard.get('sendEnabled')})")


def _ack_how(guard: dict, ack: dict) -> str:
    """How the send was acknowledged: 'bubble' (proof), the ack probe's word, or '' (uncertain)."""
    if guard.get("bubble") or ack.get("bubble"):
        return "bubble"
    return str(ack.get("ack") or "")


def _settle_uncertain(job: FfJob, obs: dict, polls: int) -> None:
    """Page evidence decides a lost ack: bubble = sent; our prompt still typed = NOT sent."""
    if obs.get("bubble"):
        job.uncertain = False
        job.journal.update(job.corr, submit_ack=True)
        log(job, "submit confirmed late (JOB-ID message visible)")
        return
    if polls < UNCERTAIN_POLLS:
        return
    if obs.get("composer_sha") == job.prompt_sha:
        raise JobFailure("submit not delivered — the composer still holds the prompt (safe to retry)")
    raise JobFailure("submit uncertain — no JOB-ID message on the page", review=True)


def _log_rejects(job: FfJob, diag: dict, seen: set) -> None:
    """RESULT candidate rejected (wrong JOB-ID) — one line per distinct set."""
    key = tuple(diag.get("mismatch") or ())
    if key and key not in seen:
        seen.add(key)
        log(job, f"result candidate rejected — JOB-ID {', '.join(key)} ≠ {job.corr}", "warn")


def _found_src(job: FfJob, obs: dict) -> str:
    diag = obs.get("diag") or {}
    if obs.get("found") and is_job_id_match(diag):
        return extract_src(diag) or ""
    return ""


async def _observe(job: FfJob) -> dict:
    """One bounded observe macro; {} when it gave no answer."""
    phase = uv_job.probe_macro(job.corr, "observe",
                               js.observe_js(job.corr, job.baseline, OBSERVE_WINDOW_MS, in_scope(job)),
                               timeout_sec=OBSERVE_WINDOW_MS // 1000 + 60)
    return (await run_macro(job, phase, required=False)).get("observe") or {}


class _WaitClock:
    """The generation deadline; a manual security wait extends it (Chrome's cap rule)."""

    def __init__(self, seconds: int):
        self.seconds, self.deadline = seconds, time.monotonic() + seconds
        self.polls, self.misses, self.seen = 0, 0, set()

    def expired(self) -> bool:
        return time.monotonic() > self.deadline


async def _poll_once(job: FfJob, clock: _WaitClock) -> str:
    """One observe round → the correlated src or ''; raises on a decided failure."""
    obs = await _observe(job)
    if not obs:
        clock.misses += 1
        if clock.misses >= MISSES_ALLOWED:
            raise JobFailure("observe macro failed repeatedly", review=True)
        return ""
    if obs.get("security"):
        clock.deadline += await wait_security(job, restore="generation")
        return ""
    clock.polls += 1
    if job.uncertain:
        _settle_uncertain(job, obs, clock.polls)
    error = match_page_error(str(obs.get("errors") or ""), job.err_base)
    if error:
        raise JobFailure(error)
    _log_rejects(job, obs.get("diag") or {}, clock.seen)
    return _found_src(job, obs)


async def phase_wait(job: FfJob) -> None:
    """WAIT_OUTPUT: poll until THIS job's result is ready, or the timeout → needs_review."""
    clock = _WaitClock(timeout_s(job, "generation", 180))
    advance(job, JobStatus.WAITING_GENERATION.value)
    mark_pool(job, "generation")
    emit(job, "WAIT_OUTPUT", "running", f"Waiting for generation — timeout {clock.seconds * 1000}ms")
    while not job.src:
        if cancel_requested(job.bridge):
            raise JobCancelled()
        if clock.expired():
            raise JobFailure(f"generation timed out after {clock.seconds}s — result uncertain", review=True)
        job.src = await _poll_once(job, clock)
    emit(job, "WAIT_OUTPUT", "success", f"Output {job.src[:60]}")
    advance(job, JobStatus.OUTPUT_DETECTED.value, output_src=job.src)


async def _fetch(job: FfJob) -> bytes:
    """FETCH_TRIES GETs of the correlated src (3 s apart, Chrome's settle delay)."""
    timeout, last = timeout_s(job, "download", 60), ""
    for attempt in range(1, FETCH_TRIES + 1):
        await asyncio.sleep(FETCH_SETTLE_S)
        try:
            return await asyncio.to_thread(out.fetch, job.src, timeout)
        except out.OutputError as exc:
            last = str(exc)
            log(job, f"download invalid (attempt {attempt}/{FETCH_TRIES}): {last}", "warn")
    raise JobFailure(f"download failed: {last}", review=True)


def _save(job: FfJob, data: bytes, ext: str):
    """SAVING checkpoint (target recorded) → atomic `_AI` save beside the source."""
    spec = out.output_spec(settings_of(job), ext)
    try:
        return out.save_beside(job.img.absolute_path, data, spec)
    except out.OutputError as exc:
        raise JobFailure(str(exc), review=True) from exc


async def phase_collect(job: FfJob) -> None:
    """DOWNLOAD → VALIDATE → SAVE; the bytes are staged before any save attempt."""
    advance(job, JobStatus.DOWNLOADING.value)
    emit(job, "DOWNLOAD", "running", "download started")
    data = await _fetch(job)
    staged = out.stage_bytes(job_dir(job), data)
    job.journal.update(job.corr, download_path=str(staged), bytes_sha256=out.sha256(data))
    emit(job, "DOWNLOAD", "success", f"Downloaded {len(data)}")
    await finish_save(job, data)


async def finish_save(job: FfJob, data: bytes) -> None:
    """VALIDATE + SAVE from secured bytes (also the recovery's re-save entry)."""
    advance(job, JobStatus.VALIDATING.value)
    try:
        ext = out.validate_image(data)
    except out.OutputError as exc:
        raise JobFailure(f"download invalid: {exc}", review=True) from exc
    emit(job, "VALIDATE", "success", f"Valid {ext} {len(data)} bytes")
    advance(job, JobStatus.SAVING.value)
    emit(job, "SAVE", "running", "atomic save started")
    path = await asyncio.to_thread(_save, job, data, ext)
    job.img.output_path = str(path)
    advance(job, JobStatus.COMPLETED.value, saved_path=str(path))
    emit(job, "SAVE", "success", f"Saved {path.name}")
