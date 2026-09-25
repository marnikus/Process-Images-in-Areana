"""Wait for a result that belongs to this job, then download and save (I-65).

A timed-out wait does not resubmit. An uncertain send with no correlated
result is needs_review, never completed.

Imports: sibling modules only.
"""

from __future__ import annotations

from pathlib import Path

from app.core.enums import ImageStatus

from . import checkpoint, phases, save, steps


def _now(env) -> float:
    clock = env.clock
    if clock is None:
        import time
        return time.monotonic()
    return float(clock.monotonic())


async def _nap(env, seconds: float) -> None:
    sleep = env.sleep
    if sleep is None:
        import asyncio
        sleep = asyncio.sleep
    await sleep(seconds)


def _log_corr(env, verdict) -> None:
    if verdict.kind == "ok":
        phases.say(env, "result candidate", verdict.src[:80])
        phases.say(env, "correlated", verdict.reason)
        return
    if verdict.kind == "rejected":
        phases.say(env, "rejected", verdict.reason)
        return
    if verdict.kind == "review":
        phases.say(env, "result candidate", verdict.reason)


def _note_fresh_miss(book: dict, verdict) -> None:
    """A fresh src that is not this job is remembered — timeout then needs review."""
    if verdict.kind == "rejected" and "not the current job" in verdict.reason:
        book["saw_uncorrelated"] = True


async def _paused_or_cancel(env) -> str:
    """Wait out a pause. Cancel during the pause is cancel-after (already sent)."""
    while bool(getattr(env.job.bridge, "_pause_requested", False)):
        if _cancelled(env):
            return "cancel_after"
        await _nap(env, env.poll)
    return "cancel_after" if _cancelled(env) else ""


async def wait_generation(env, book: dict) -> str:
    """Poll until a correlated result, a review, cancel-after, or timeout."""
    phases.say(env, "Waiting for generation", "")
    _mark_generation(env)
    deadline = _now(env) + float(env.timeout)
    while _now(env) < deadline:
        stopped = await _paused_or_cancel(env)
        if stopped:
            return stopped
        snap = await phases.probe(env)
        if snap.get("security"):
            _waiting_user(env)
            await _nap(env, env.poll)
            deadline = _now(env) + float(env.timeout)
            continue
        _back_to_generation(env)
        verdict = steps.correlate(book.get("baseline") or [], snap.get("results") or [], env.corr_id)
        _log_corr(env, verdict)
        _note_fresh_miss(book, verdict)
        if verdict.kind == "ok":
            return _correlated(env, book, verdict.src)
        if verdict.kind == "review":
            book["review_reason"] = verdict.reason
            return "review"
        await _nap(env, env.poll)
    phases.say(env, "Wait failed: timeout", "")
    book["phase"] = "timed_out"
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    return "timeout"


def _cancelled(env) -> bool:
    return bool(getattr(env.job.bridge, "_cancel_requested", False))


def _correlated(env, book: dict, src: str) -> str:
    book["result_src"] = src
    book["phase"] = "result_correlated"
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    phases.say(env, "Output", src[:80])
    return "ready"


def _mark_generation(env) -> None:
    """Chrome's waiting_generation — the page is working, not free."""
    try:
        env.job.pool.mark_waiting(env.page.tab_id, "generation")
    except Exception:
        return
    phases.say(env, "pool waiting_generation", "")


def _waiting_user(env) -> None:
    """Chrome's waiting_captcha — the log also names it waiting_user."""
    if getattr(env, "security_logged", False):
        return
    env.security_logged = True
    try:
        env.job.pool.mark_waiting(env.page.tab_id, "captcha")
    except Exception:
        return
    phases.say(env, "waiting_user", "manual security action (waiting_captcha)")
    phases.say(env, "pool waiting_captcha", "")


def _back_to_generation(env) -> None:
    page = env.job.pool.get_page(env.page.tab_id)
    if page is None or str(getattr(page, "status", "")) != "waiting_captcha":
        return
    env.security_logged = False
    try:
        env.job.pool.mark_waiting(env.page.tab_id, "generation")
    except Exception:
        return
    phases.say(env, "pool waiting_generation", "security cleared")


def _stash(env, data: bytes) -> Path:
    """Keep downloaded bytes so a crash after download can still save them."""
    dest = Path(env.job.img.absolute_path).with_name(
        f".{Path(env.job.img.absolute_path).name}.arena-download")
    dest.write_bytes(data)
    return dest


def _review_or_fail(env, book: dict, reason: str) -> None:
    if book.get("submit_uncertain"):
        env.job.img.status = ImageStatus.NEEDS_REVIEW.value
        env.job.img.error = reason
        book["phase"] = "needs_review"
        checkpoint.save_book(env.job.bridge, env.job.img.id, book)
        phases.say(env, "pool error", reason)
        return
    env.job.img.status = ImageStatus.FAILED.value
    env.job.img.error = reason
    phases.say(env, "pool error", reason)


async def download_and_save(env, book: dict) -> None:
    """Download the correlated src, or finish a download that already landed."""
    if book.get("download_path") and Path(book["download_path"]).is_file():
        await _save_file(env, book, Path(book["download_path"]).read_bytes())
        return
    phases.say(env, "Download started", str(book.get("result_src") or "")[:80])
    reply = await phases.act(env, "download", {"src": book.get("result_src") or ""})
    data = reply.get("data") or {}
    problem = steps.download_problem(data)
    if problem:
        phases.say(env, "Download failed", problem)
        _review_or_fail(env, book, problem)
        return
    raw = phases.offer_bytes(data)
    bad = save.image_problem(raw)
    if bad:
        phases.say(env, "Download failed", bad)
        _review_or_fail(env, book, bad)
        return
    phases.say(env, "Downloaded", str(len(raw)))
    path = _stash(env, raw)
    book["download_path"] = str(path)
    book["phase"] = "downloaded"
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    await _save_file(env, book, raw)


async def _save_file(env, book: dict, raw: bytes) -> None:
    bad = save.image_problem(raw)
    if bad:
        phases.say(env, "Download failed", bad)
        _review_or_fail(env, book, bad)
        return
    phases.say(env, "atomic save started", Path(env.job.img.absolute_path).name)
    checkpoint.mark_saving(env.job.img.absolute_path)
    book["phase"] = "saving"
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    try:
        dest = save.write_output(env.job.bridge, env.job.img.absolute_path, raw)
    except OSError as exc:
        phases.say(env, "Save failed", save.save_error_name(exc))
        env.job.img.status = ImageStatus.FAILED.value
        env.job.img.error = save.save_error_name(exc)
        return
    _mark_saved(env, book, dest)


def _mark_saved(env, book: dict, dest: Path) -> None:
    env.job.img.output_path = str(dest)
    env.job.img.status = ImageStatus.COMPLETED.value
    env.job.img.error = None
    book["phase"] = "saved"
    book["output_path"] = str(dest)
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    phases.say(env, "Saved", dest.name)
    _persist_queue(env)
    checkpoint.clear_saving(env.job.img.absolute_path)


def _persist_queue(env) -> None:
    """Queue write after the file exists. A miss leaves the saving stamp."""
    try:
        env.job.bridge.state.recalculate_progress()
        env.job.bridge._save_arena()
    except Exception:
        phases.say(env, "Save failed", "state persistence interrupted")
