"""Firefox image job — the pre-submit phases (design §4/§6.1/§6.2, 2026-09-25).

Baseline → (manual security wait) → attach + positive verify → prompt insert +
exact readback. Every phase writes its journal checkpoint through
`JobJournal.advance` (validated against `JOB_TRANSITIONS`) and emits Chrome's
block event (`OBSERVE_BASELINE`, `CHECK_SECURITY`, `ATTACH_IMAGE`,
`VERIFY_ATTACHMENT`, `INSERT_PROMPT`, `VERIFY_PROMPT`). Nothing here submits:
every failure below is safe to retry (no message reached the site).

The New Chat reset (`reset_page`) lives here too: it is the stale-composer
cleanup before a job and the post-job reset the finish path calls (§15).
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from app.browser.uivision import job_macros as uv_job
from app.browser.uivision import job_scripts as js
from app.core.enums import JobStatus
from app.services.captcha.policy import pause_cap_seconds
from app.services.cooldown_service import note_captcha_event
from app.services.firefox_job_journal import is_post_submit
from app.services.firefox_job_ctx import (
    FfJob, JobFailure, emit, in_scope, log, mark_pool, run_macro,
)

SECURITY_POLL_S = 5
ATTACH_WAIT_MS = 8000
CLEAN_WAIT_MS = 15000


def advance(job: FfJob, status: str, **fields) -> None:
    """Journal checkpoint; a refused move is a bug → honest failure (never silent)."""
    if not job.journal.advance(job.corr, status, **fields):
        current = (job.journal.get(job.corr) or {}).get("status")
        raise JobFailure(f"illegal job transition {current} → {status}", review=_after_send(job))


def _after_send(job: FfJob) -> bool:
    return is_post_submit(job.journal.get(job.corr))


def utf16_len(text: str) -> int:
    """JS `String.length` (UTF-16 code units) — what the page reports back."""
    return len(text.encode("utf-16-le")) // 2


def prompt_text(raw: str) -> str:
    """The prompt as a textarea holds it (CRLF → LF)."""
    return str(raw or "").replace("\r\n", "\n").replace("\r", "\n")


def sha_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def wait_security(job: FfJob, restore: str = "busy") -> float:
    """Manual security check: `waiting_captcha` until cleared or the cap (never solves)."""
    mark_pool(job, "captcha")
    emit(job, "CHECK_SECURITY", "running", "security check visible — waiting for the user "
                                         "(Firefox never solves, RULE 20)")
    cap, t0 = pause_cap_seconds(job.bridge), time.monotonic()
    while True:
        reply = (await run_macro(job, uv_job.probe_macro(job.corr, "security",
                                                         js.security_js(True)))).get("security", {})
        if not reply.get("security"):
            note_captcha_event(job.pool, job.tab_id, job.bridge, source="firefox job")
            mark_pool(job, restore)
            emit(job, "CHECK_SECURITY", "success", "Security done")
            return time.monotonic() - t0
        if time.monotonic() - t0 > cap:
            raise JobFailure(f"security check not cleared within {cap}s", review=_after_send(job))
        await asyncio.sleep(SECURITY_POLL_S)


async def _baseline_reply(job: FfJob) -> dict:
    phase = uv_job.probe_macro(job.corr, "baseline", js.baseline_js(in_scope(job)))
    data = (await run_macro(job, phase)).get("baseline")
    if not isinstance(data, dict):
        raise JobFailure("baseline probe gave no answer")
    if data.get("security") and in_scope(job):
        await wait_security(job)
        return await _baseline_reply(job)
    return data


async def _clean_composer(job: FfJob, data: dict) -> dict:
    """A leftover attachment poisons the job: New Chat once, re-baseline, else fail."""
    if not data.get("previews"):
        return data
    log(job, f"stale attachment in the composer ({len(data['previews'])}) — New Chat first", "warn")
    await reset_page(job)
    data = await _baseline_reply(job)
    if data.get("previews"):
        raise JobFailure("stale attachment in composer — New Chat did not clear it")
    return data


async def phase_baseline(job: FfJob) -> None:
    """OBSERVE_BASELINE: outputs already on the page (the correlation's old set)."""
    emit(job, "OBSERVE_BASELINE", "running", "capturing the page baseline")
    data = await _clean_composer(job, await _baseline_reply(job))
    if int(data.get("composer_len", -1)) < 0:
        raise JobFailure("composer not found — the page is not ready")
    job.baseline = {"srcs": list(data.get("srcs") or []), "outputs": list(data.get("outputs") or [])}
    job.err_base = str(data.get("errors") or "")
    advance(job, JobStatus.BASELINE_CAPTURED.value, baseline=job.baseline)
    emit(job, "OBSERVE_BASELINE", "success", f"Baseline {len(job.baseline['srcs'])}")


def check_attachment(job: FfJob, reply: dict) -> None:
    """Exactly ONE visible preview, and it carries our unique staged name (§6.1)."""
    previews = list(reply.get("previews") or [])
    ours = [p for p in previews if p.get("alt") == job.staged_name]
    if len(ours) == 1 and len(previews) == 1:
        return
    if len(ours) > 1 or (ours and len(previews) > 1):
        raise JobFailure(f"multiple attachments in the composer ({len(previews)})")
    if previews:
        raise JobFailure(f"wrong attachment preview: {previews[0].get('alt') or 'unnamed blob'}")
    raise JobFailure("attachment not visible after the upload")


async def _attach_once(job: FfJob) -> dict:
    phase = uv_job.attach_macro(job.corr, job.staged, js.attach_wait_js(job.staged_name, ATTACH_WAIT_MS))
    return (await run_macro(job, phase)).get("attach") or {}


async def phase_attach(job: FfJob) -> None:
    """ATTACH_IMAGE (native dialog) + VERIFY_ATTACHMENT (unique name); one retry when nothing appeared."""
    advance(job, JobStatus.ATTACHING.value, staged_upload=job.staged)
    emit(job, "ATTACH_IMAGE", "running", f"upload started {job.staged_name}")
    reply = await _attach_once(job)
    if not reply.get("previews"):
        log(job, "no preview after the dialog — one more upload attempt", "warn")
        reply = await _attach_once(job)
    emit(job, "ATTACH_IMAGE", "success", "dialog closed")
    check_attachment(job, reply)
    advance(job, JobStatus.ATTACHMENT_VERIFIED.value)
    emit(job, "VERIFY_ATTACHMENT", "success", f"verified preview {job.staged_name}")


def _prompt_ok(job: FfJob, reply: dict, text: str) -> bool:
    return (bool(reply.get("ok")) and reply.get("sha256") == job.prompt_sha
            and int(reply.get("len", -1)) == utf16_len(text))


async def phase_prompt(job: FfJob) -> None:
    """INSERT_PROMPT (native setter) + VERIFY_PROMPT (exact + SHA-256), one re-insert."""
    text = prompt_text(job.prompt)
    job.prompt_sha = sha_of(text)
    emit(job, "INSERT_PROMPT", "running", f"inserting {utf16_len(text)} chars")
    advance(job, JobStatus.PROMPT_INSERTED.value, prompt_sha256=job.prompt_sha)
    reply: dict = {}
    for attempt in (1, 2):
        phase = uv_job.probe_macro(job.corr, "prompt", js.prompt_js(text))
        reply = (await run_macro(job, phase)).get("prompt") or {}
        if _prompt_ok(job, reply, text):
            break
        log(job, f"prompt readback mismatch (attempt {attempt}: len {reply.get('len')} "
                 f"vs {utf16_len(text)}{', ' + reply['error'] if reply.get('error') else ''})", "warn")
    else:
        raise JobFailure(f"prompt readback mismatch (len {reply.get('len')} ≠ {utf16_len(text)})")
    emit(job, "INSERT_PROMPT", "success", f"inserted {utf16_len(text)} chars")
    advance(job, JobStatus.PROMPT_VERIFIED.value)
    emit(job, "VERIFY_PROMPT", "success", f"verified sha {job.prompt_sha[:12]}")


async def reset_page(job: FfJob) -> tuple:
    """XClick New Chat + the clean-page check → (ok, reason); never raises."""
    try:
        phase = uv_job.reset_macro(job.corr, js.clean_js(CLEAN_WAIT_MS))
        reply = (await run_macro(job, phase)).get("reset") or {}
    except JobFailure as exc:
        return False, str(exc)
    if reply.get("clean"):
        return True, "New Chat — clean page verified"
    return False, f"page not clean after New Chat: {reply.get('state')}"

