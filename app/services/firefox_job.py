"""Firefox image job — one claimed image on one Firefox pool tab (design D-1, 2026-09-25).

The dispatcher claims a Firefox page exactly like a Chrome one and hands the
job here; bookkeeping (image status, Job History, count, cooldown) stays the
dispatcher's and `cooldown_service`'s — the SAME code Chrome runs.

Pipeline: source check → staged copy → baseline → attach → prompt → SUBMIT
(once) → wait / correlate → collect (download, validate, atomic `_AI` save).
Between the pre-submit phases a Pause holds at the last verified checkpoint
and re-verifies it on resume; Cancel before the submit ends safely (nothing
sent), Cancel after the submit keeps the evidence and settles needs_review
(no New Chat, no count). A started phase macro always runs to its end.

Settling: an uncertain outcome is needs_review only once the submit line is
crossed (`_settle_review`, record + bytes kept); anything else is a plain
failure that forgets the record (`_settle_failed`).

`run_job` returns a `Verdict`; `after_result` applies what `_handle_result`
cannot know (needs_review, a save that finished despite a Cancel);
`lane_reset` is the finish seam's New Chat (Ui.Vision XClick + clean check).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from typing import Any

from app.browser.uivision import job_macros as uv_job
from app.browser.uivision import job_scripts as js
from app.core.enums import ImageStatus, JobStatus
from app.services import firefox_lane as fl
from app.services import firefox_job_host as host
from app.services.firefox_job_ctx import (
    FfJob, JobCancelled, JobFailure, cancel_requested, complete, log, run_macro,
)
from app.services.firefox_job_journal import is_post_submit, job_folder, journal_of
from app.services.firefox_job_phases import (
    check_attachment, phase_attach, phase_baseline, phase_prompt, reset_page,
)
from app.services.firefox_job_result import phase_collect, phase_submit, phase_wait
from app.services.firefox_job_upload import check_source, drop_staged, stage_upload
from app.services.job_history import record_dispatch_result

logger = logging.getLogger("arena")

CANCEL_REVIEW = "Cancelled after submit — result kept for review"
PAUSE_POLL_S = 0.5


@dataclass
class JobStart:
    """What the dispatcher hands over (RULE 16 parameter budget)."""

    bridge: Any
    pool: Any
    tab_id: str
    img: Any
    corr: str
    prompt: str


@dataclass
class Verdict:
    failed: bool
    err: str = ""
    review: bool = False


def _paused(bridge) -> bool:
    return bool(getattr(bridge, "_pause_requested", False))


async def _reverify(job: FfJob) -> None:
    """After a pause: the verified attachment / prompt must still be on the page."""
    status = (job.journal.get(job.corr) or {}).get("status")
    if status not in (JobStatus.ATTACHMENT_VERIFIED.value, JobStatus.PROMPT_VERIFIED.value):
        return
    phase = uv_job.probe_macro(job.corr, "observe", js.observe_js(job.corr, job.baseline, 0, False))
    obs = (await run_macro(job, phase)).get("observe") or {}
    check_attachment(job, obs)
    if status == JobStatus.PROMPT_VERIFIED.value and obs.get("composer_sha") != job.prompt_sha:
        raise JobFailure("prompt changed during the pause — not sent (safe to retry)")
    log(job, f"checkpoint {status} re-verified — continuing")


async def checkpoint(job: FfJob) -> None:
    """Pre-submit hold point: Cancel ends here; Pause waits here, then re-verifies."""
    if cancel_requested(job.bridge):
        raise JobCancelled()
    if not _paused(job.bridge):
        return
    status = (job.journal.get(job.corr) or {}).get("status")
    log(job, f"⏸ paused before submit at {status} — resumes from this verified checkpoint")
    while _paused(job.bridge) and not cancel_requested(job.bridge):
        await asyncio.sleep(PAUSE_POLL_S)
    if cancel_requested(job.bridge):
        raise JobCancelled()
    log(job, "▶ resumed — re-verifying the checkpoint")
    await _reverify(job)


async def _pipeline(job: FfJob) -> None:
    error = check_source(job.img.absolute_path)
    if error:
        raise JobFailure(error)
    job.staged = str(stage_upload(host.config_dir(job.bridge), job.img.absolute_path, job.corr))
    await checkpoint(job)
    for phase in (phase_baseline, phase_attach, phase_prompt):
        await phase(job)
        await checkpoint(job)
    await phase_submit(job)
    await phase_wait(job)
    await complete(phase_collect(job))


def _forget(job: FfJob) -> None:
    """Drop the journal record + the job folder (nothing left to recover)."""
    job.journal.drop(job.corr)
    shutil.rmtree(job_folder(job.bridge, job.corr), ignore_errors=True)


def _settle_ok(job: FfJob) -> Verdict:
    _forget(job)
    return Verdict(False)


def _settle_failed(job: FfJob, message: str) -> Verdict:
    """Nothing reached the site (or nothing is worth keeping): record + folder forgotten."""
    job.journal.advance(job.corr, JobStatus.FAILED.value, error=message)
    _forget(job)
    return Verdict(True, message)


def _settle_review(job: FfJob, message: str, shown: str) -> Verdict:
    """The site may have the message: keep the record + bytes as evidence, no New Chat.

    Decided by the submit line, never by whether the journal accepted the write —
    needs_review is reachable from exactly the post-submit statuses (pinned by
    `test_needs_review_is_reachable_exactly_from_the_post_submit_statuses`).
    """
    job.journal.advance(job.corr, JobStatus.NEEDS_REVIEW.value, error=message, needs_review=True)
    job.review = job.skip_reset = True
    log(job, f"⚠ {shown}", "warn")
    return Verdict(True, shown, True)


def _sent(job: FfJob) -> bool:
    return is_post_submit(job.journal.get(job.corr))


def _settle_failure(job: FfJob, message: str, review: bool) -> Verdict:
    """An uncertain outcome after the submit is needs_review; anything else a plain failure."""
    if review and _sent(job):
        return _settle_review(job, message, f"needs review — {message}")
    return _settle_failed(job, message)


def _settle_cancel(job: FfJob) -> Verdict:
    """After the submit: evidence kept, needs_review, no New Chat; before: nothing sent."""
    if _sent(job):
        return _settle_review(job, CANCEL_REVIEW, CANCEL_REVIEW)
    log(job, "Cancelled before submit — nothing was sent", "warn")
    return _settle_failed(job, "Cancelled")


def _mark_review(bridge, img, message: str) -> None:
    img.status, img.error = ImageStatus.NEEDS_REVIEW.value, message
    host.persist(bridge)


def lane_reset(job: FfJob):
    """The finish seam's New Chat: skipped while the page is review evidence."""
    async def _reset() -> tuple:
        try:
            if job.skip_reset:
                log(job, "New Chat skipped — the page is kept as review evidence")
                return True, "skipped (needs review)"
            ok, reason = await reset_page(job)
            if ok:
                log(job, reason)
            return ok, reason
        finally:
            fl.note_job_end()
    return _reset


def _new_job(start: JobStart) -> FfJob:
    page = start.pool.get_page(start.tab_id)
    if page is None:
        raise JobFailure("tab left the pool before the job started")
    journal = journal_of(start.bridge)
    image_path = str(start.img.absolute_path)
    journal.create(start.corr, tab_id=start.tab_id, image_id=getattr(start.img, "id", ""),
                   image_path=image_path)
    job = FfJob(bridge=start.bridge, pool=start.pool, page=page, img=start.img,
                corr=start.corr, prompt=start.prompt, journal=journal)
    _supersede(job, image_path)
    return job


def _supersede(job: FfJob, image_path: str) -> None:
    """A re-queued image replaces its older records: never collect their old results later."""
    for old in job.journal.supersede(image_path, keep=job.corr):
        shutil.rmtree(job_folder(job.bridge, old), ignore_errors=True)
        log(job, f"older record [{old}] of this image superseded — its result is no longer collected")


async def _run(job: FfJob) -> Verdict:
    try:
        await _pipeline(job)
        return _settle_ok(job)
    except JobCancelled:
        return _settle_cancel(job)
    except JobFailure as exc:
        return _settle_failure(job, str(exc), exc.review)
    except asyncio.CancelledError:
        if _settle_cancel(job).review:
            _mark_review(job.bridge, job.img, CANCEL_REVIEW)
        raise
    except Exception as exc:  # a bug must still settle honestly (RULE 4)
        logger.exception("Firefox job crashed")
        return _settle_failure(job, f"Firefox job crashed: {exc}", True)


async def run_job(start: JobStart, reset_out: list) -> Verdict:
    """Run one image job; `reset_out` receives the finish seam's New Chat first."""
    try:
        job = _new_job(start)
    except JobFailure as exc:
        return Verdict(True, str(exc))
    reset_out.append(lane_reset(job))
    await fl.job_gap(job.bridge)
    try:
        return await _run(job)
    finally:
        drop_staged(job.staged)
        fl.note_job_end()  # fallback stamp; the finish seam's New Chat (lane_reset) stamps again, later


def after_result(ctx, verdict: Verdict) -> None:
    """What `_handle_result` cannot know: needs_review, or a save that beat the Cancel."""
    cancelled = cancel_requested(ctx.bridge)
    if verdict.review:
        _mark_review(ctx.bridge, ctx.img, verdict.err)
    elif not verdict.failed and cancelled:
        ctx.img.status, ctx.img.error = ImageStatus.COMPLETED.value, None
        host.persist(ctx.bridge)
    else:
        return
    if cancelled:
        record_dispatch_result(ctx)  # `_handle_result` returned before its history row
