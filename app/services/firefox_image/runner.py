"""Drive one Firefox image job from the shared queue (I-65).

The dispatcher has already marked the page busy. This module uploads, verifies,
submits once, correlates, downloads and saves. It does not increment the job
counter — that happens only in the success finish, after the file exists.

Imports: sibling phases/wait/steps/checkpoint/log. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import ImageStatus

from . import checkpoint, log, phases, steps, wait


@dataclass
class RunOptions:
    """Seams for one run. Tests pass a clock; production leaves them empty."""

    corr_id: str = ""
    prompt: str = ""
    transport: object = None
    clock: object = None
    sleep: object = None
    timeout: object = None


@dataclass
class JobEnv:
    """One job's inputs. The clock and sleep seams keep tests off the wall clock."""

    job: object
    page: object
    corr_id: str
    prompt: str
    transport: object
    clock: object = None
    sleep: object = None
    timeout: float = 600.0
    poll: float = 0.4


def _timeout_of(bridge, given) -> float:
    if given is not None:
        return float(given)
    try:
        return float(bridge.config.get_state("watcher_generation_timeout_sec", 600))
    except Exception:
        return 600.0


def _cancelled(env) -> bool:
    return bool(getattr(env.job.bridge, "_cancel_requested", False))


def _paused(env) -> bool:
    return bool(getattr(env.job.bridge, "_pause_requested", False))


async def honour_pause(env) -> str:
    """Wait out a pause. Cancel during the pause is cancel-before (no submit)."""
    while _paused(env):
        if _cancelled(env):
            return "cancel"
        await wait._nap(env, env.poll)
    return ""


def _fail(env, reason: str) -> None:
    env.job.img.status = ImageStatus.FAILED.value
    env.job.img.error = reason
    log.phase(env.job.bridge, env.corr_id, "pool error", reason)


def _review(env, book: dict, reason: str) -> None:
    env.job.img.status = ImageStatus.NEEDS_REVIEW.value
    env.job.img.error = reason
    book["phase"] = "needs_review"
    book["error"] = reason
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    log.phase(env.job.bridge, env.corr_id, "pool error", reason)


def _apply_gate(env, book: dict, kind: str) -> None:
    if kind == "cancel_after":
        _review(env, book, "cancel after submit — result uncertain")
        return
    _fail(env, "Cancelled")


async def _gate(env, book: dict) -> str:
    paused = await honour_pause(env)
    if paused:
        return paused
    return steps.control_kind(_cancelled(env), bool(book.get("submitted")))


async def _gated(env, book: dict, step) -> bool:
    kind = await _gate(env, book)
    if kind and kind != "run":
        _apply_gate(env, book, kind)
        return False
    return await step(env, book)


def _select(env) -> None:
    env.page.current_job_id = env.corr_id
    label = getattr(env.page, "label", "") or env.page.tab_id
    attempt = getattr(env.job.img, "attempt_count", 0)
    log.phase(env.job.bridge, env.corr_id, "worker/job/attempt selected",
              f"{label} job {env.corr_id} attempt {attempt}")
    log.phase(env.job.bridge, env.corr_id, "pool BUSY", env.page.tab_id)


def _reconcile(env) -> bool:
    source = env.job.img.absolute_path
    book = checkpoint.load_book(env.job.bridge, env.job.img.id)
    sibling = steps.sibling_output(source)
    if not steps.should_reconcile(env.job.img.status, book.get("phase") or "",
                                  checkpoint.saving_marked(source), sibling):
        return False
    env.job.img.output_path = str(sibling)
    env.job.img.status = ImageStatus.COMPLETED.value
    env.job.img.error = None
    log.phase(env.job.bridge, env.corr_id, "Saved",
              "reconciled existing output — not resubmitting")
    checkpoint.clear_saving(source)
    return True


async def _before_submit(env, book: dict) -> bool:
    if book.get("phase") not in ("attachment_verified", "prompt_verified"):
        if not await _gated(env, book, phases.attach):
            return False
    if book.get("phase") != "prompt_verified":
        if not await _gated(env, book, phases.insert_prompt):
            return False
    return await _gated(env, book, phases.submit_once)


async def _after_submit(env, book: dict) -> None:
    if book.get("phase") == "downloaded" or book.get("download_path"):
        await wait.download_and_save(env, book)
        return
    if book.get("result_src"):
        await wait.download_and_save(env, book)
        return
    outcome = await wait.wait_generation(env, book)
    await _finish_wait(env, book, outcome)


async def _finish_wait(env, book: dict, outcome: str) -> None:
    if outcome == "ready":
        await wait.download_and_save(env, book)
        return
    if outcome == "review":
        _review(env, book, book.get("review_reason") or "uncertain result")
        return
    if outcome == "cancel_after":
        _review(env, book, "cancel after submit — result uncertain")
        return
    if book.get("submit_uncertain") or book.get("saw_uncorrelated"):
        reason = "uncertain result" if book.get("submit_uncertain") else "uncorrelated result"
        _review(env, book, reason)
        return
    _fail(env, "generation timed out")


async def _run_book(env, book: dict) -> None:
    if book.get("submitted"):
        if book.get("submit_uncertain"):
            log.phase(env.job.bridge, env.corr_id, "Submit acknowledgment lost",
                      "already submitted — not resubmitting")
        await _after_submit(env, book)
        return
    if not await _before_submit(env, book):
        return
    await _after_submit(env, book)


def _env_for(job, page, options: RunOptions) -> JobEnv:
    """Fill the production transport when the caller did not inject one."""
    transport = options.transport
    if transport is None:
        from .transport import MacroTransport
        transport = MacroTransport(job.bridge, page)
    return JobEnv(job=job, page=page, corr_id=options.corr_id or "", prompt=options.prompt or "",
                  transport=transport, clock=options.clock, sleep=options.sleep,
                  timeout=_timeout_of(job.bridge, options.timeout))


async def run_firefox_image(job, page, options: RunOptions = None) -> None:
    """One queued image on one Firefox worker. Does not close the tab."""
    env = _env_for(job, page, options or RunOptions())
    if _reconcile(env):
        return
    problem = steps.source_problem(job.img.absolute_path)
    if problem:
        _fail(env, problem)
        return
    _select(env)
    book = steps.restore_book(checkpoint.load_book(job.bridge, job.img.id))
    await _run_book(env, book)
