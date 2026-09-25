# ideal-size: ~460 lines reason=one image job's stage machine — preflight/resume/prepare/submit/collect/save share the JobRequest/JobOutcome/journal vocabulary and always change together; splitting them would scatter the one flow the design documents as five stages (RULE 18.2)
"""The Firefox image job — attach → prompt → one submit → correlate → save.

The lane's stage machine (owner brief steps 14–19). One job:

1. **preflight** — the source image exists and is a format the site accepts
   (a missing/unsupported file is a named failure before any macro runs);
2. **recovery** — the journal, the output file and (only then) the page decide
   whether the job is already done, needs finishing, can be collected without a
   second submit, or may start fresh (`firefox_recovery`);
3. **prepare** — one Ui.Vision run: baseline, (bounded) stale-tile cleanup, the
   native attach (`XClick` → `XType` path → Enter), the attachment proof, the
   prompt insert + read-back and the pre-submit checkpoint;
4. **checkpoint** — Pause/Stop/Cancel act here, *before* anything is submitted;
5. **submit** — the same prompt/attachment/guard re-verified, then exactly one
   guarded `XClick` on Send (the macro records the click count), then the wait
   for a candidate that is new and correlated to this job's `[JOB-ID: …]`;
6. **collect + save** — the shared HTTPS fetch first, the page's own fetch second
   (a `blob:` src has no other route), PIL validation, the staging file and the
   atomic `_AI` save beside the source (`firefox_result`).

Every phase logs the same states Chrome's blocks log (baseline, attachment
verified, prompt verified, submit intent/submitted/uncertain, generation,
candidate/correlated/rejected, download started/completed/invalid, atomic save);
ambiguity is `needs_review` and the page keeps its evidence — the job is never
rounded to "completed".

Imports: services → browser (lane, uivision, page_pool) + the sibling modules.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from app.browser.page_pool import tab_label_of
from app.browser.uivision import job_macro, job_replies

from . import firefox_journal as journal
from . import firefox_recovery as recovery
from . import firefox_result as result
from .firefox_lane import run_job_stage

log = logging.getLogger("arena")

SUPPORTED_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
PAUSE_POLL_SEC = 1.0
COMPLETED, FAILED, NEEDS_REVIEW, CANCELLED = "completed", "failed", "needs_review", "cancelled"


@dataclass
class JobRequest:
    """One dispatched Firefox job (the dispatcher's own correlation values)."""

    bridge: object
    page: object
    img: object
    corr_id: str
    job_id: str
    prompt: str


@dataclass
class JobOutcome:
    """What the job answered — the dispatcher maps this onto the image's state."""

    status: str
    error: str = ""
    output_path: str = ""

    @property
    def ok(self) -> bool:
        return self.status == COMPLETED

    @property
    def preserve(self) -> bool:
        """True when the page must keep its in-flight evidence (no reset, no cooldown)."""
        return self.status == NEEDS_REVIEW

    @property
    def count_job(self) -> bool:
        """Only a saved file counts as a finished job (step 14/19)."""
        return self.status == COMPLETED


@dataclass(frozen=True)
class Submission:
    """The submit stage's answer: how many clicks, and what the page showed after."""

    clicks: int
    status: str
    src: str = ""
    reason: str = ""


def _log(req: JobRequest, message: str, level: str = "info") -> None:
    """Every job line carries its correlation id (RULE 2)."""
    try:
        req.bridge._log(f"[{req.corr_id}] {message}", level)
    except Exception:
        pass


def _reporter(req: JobRequest):
    """The lane's per-step callback, tagged with this job (RULE 2/5)."""
    def report(step: str, message: str, level: str = "info") -> None:
        _log(req, f"{step}: {message}", level)
    return report


def _settings(bridge):
    return bridge.state.settings


def _pool(req: JobRequest):
    return getattr(req.bridge, "_page_pool", None)


def _label(req: JobRequest) -> str:
    try:
        return tab_label_of(_pool(req), req.page.tab_id)
    except Exception:
        return str(getattr(req.page, "tab_id", "") or "?")


def _cancelled(req: JobRequest) -> bool:
    """The operator cancelled the pass (RULE 7) — globally or for this tab."""
    if getattr(req.bridge, "_cancel_requested", False):
        return True
    try:
        from .cooldown_service import is_tab_aborted
        return bool(is_tab_aborted(_pool(req), req.page.tab_id))
    except Exception:
        return False


def _mark_waiting(req: JobRequest, kind: str) -> None:
    """Pool: busy → waiting (the manual-action state the UI shows)."""
    try:
        pool = _pool(req)
        if pool:
            pool.mark_waiting(req.page.tab_id, kind)
            req.bridge._emit_pool_status()
    except Exception:
        pass


def _failed(req: JobRequest, reason: str) -> JobOutcome:
    return JobOutcome(FAILED, error=reason)


def _review(req: JobRequest, reason: str) -> JobOutcome:
    """A human must look: keep the page's evidence and say why."""
    _log(req, f"🛑 needs review: {reason}", "warn")
    try:
        pool = _pool(req)
        if pool:
            pool.mark_error(req.page.tab_id, reason)
            req.bridge._emit_pool_status()
    except Exception:
        pass
    return JobOutcome(NEEDS_REVIEW, error=reason)


def _guard_outcome(req: JobRequest, reason: str) -> JobOutcome:
    """A security dialog is a human's job (busy → waiting_user); anything else fails."""
    if "security" in str(reason).lower():
        _mark_waiting(req, "captcha")
        _log(req, f"🛑 needs review: manual action required — {reason}", "warn")
        return JobOutcome(NEEDS_REVIEW, error=f"manual action required: {reason}")
    return _failed(req, f"submit checkpoint refused: {reason}")


def _preflight(req: JobRequest) -> JobOutcome | None:
    """The source image must exist and be one the site accepts (before any macro)."""
    path = Path(str(getattr(req.img, "absolute_path", "") or ""))
    if not path.is_file():
        return _failed(req, f"source file missing: {path}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return _failed(req, f"unsupported source type: {path.suffix or '(none)'}")
    if not str(path).isascii():
        _log(req, "⚠ non-ASCII path — XType types keystrokes; the attach proof decides", "warn")
    return None


@dataclass(frozen=True)
class StageFacts:
    """What earlier stages already proved about the page (baked into the macro)."""

    baseline: tuple = ()
    src: str = ""


def _inputs(req: JobRequest, stage: str, facts: StageFacts = StageFacts(), budget: int = 0):
    """The stage's baked-in constants (prompt, file, token, facts) and its budget."""
    name = Path(str(req.img.absolute_path)).name
    return job_macro.StageInputs(stage=stage, token=req.corr_id, image_path=str(req.img.absolute_path),
                                 file_name=name, prompt=req.prompt, baseline=tuple(facts.baseline),
                                 src=facts.src, budget_ms=budget or job_macro.budget_for(stage))


async def _stage(req: JobRequest, inputs) -> tuple:
    """One Ui.Vision stage under the lane's lock/gap; every answer parsed."""
    kind, message, lines = await run_job_stage(req.bridge, req.page, inputs, _reporter(req))
    replies = job_replies.parse(lines)
    _log(req, f"{inputs.stage} macro: {kind} — {message}", "info" if kind == "ok" else "warn")
    return kind, message, replies


def _attach_gate(req: JobRequest, replies) -> JobOutcome | None:
    """The attachment is verified only by the page: one new tile, named like the file."""
    ok, reason = job_replies.attach_verdict(replies.attach, cleaned=bool(replies.remove_sel))
    if ok:
        _log(req, f"✅ Attachment verified: {reason}", "success")
        return None
    _log(req, f"❌ Verify attachment failed: {reason}", "error")
    _log(req, "   (a native file dialog may still be open — nothing was submitted)", "warn")
    return _review(req, f"attachment not verified: {reason}")


def _prompt_gate(req: JobRequest, replies) -> JobOutcome | None:
    """The prompt is verified only by its own read-back (length + FNV-1a hash)."""
    ok, reason = job_replies.prompt_verdict(replies.prompt,
                                            expected_hash=job_replies.prompt_hash(req.prompt))
    if ok:
        _log(req, f"✅ Prompt verified: {reason}", "success")
        return None
    _log(req, f"❌ Prompt not verified: {reason}", "error")
    return _failed(req, f"prompt not verified: {reason}")


def _guard_gate(req: JobRequest, replies) -> JobOutcome | None:
    """The checkpoint that stands in front of the single Send click."""
    ok, reason = job_replies.guard_verdict(replies.guard, replies.guard_why)
    if ok:
        _log(req, "☑ submit checkpoint: prompt, one attachment and an enabled Send re-verified", "success")
        return None
    _log(req, f"❌ submit checkpoint refused: {reason}", "error")
    return _guard_outcome(req, reason)


async def _prepare(req: JobRequest, baseline: list) -> tuple:
    """The whole pre-submit half in one macro run (attach → prompt → checkpoint)."""
    kind, message, replies = await _stage(req, _inputs(req, "prepare", StageFacts(baseline=baseline)))
    if not replies.answered:
        return _review(req, f"the prepare macro answered nothing ({kind}: {message})"), baseline
    for gate in (_attach_gate, _prompt_gate, _guard_gate):
        failure = gate(req, replies)
        if failure is not None:
            return failure, baseline
    updated = list(job_replies.baseline_of(replies) or baseline)
    _log(req, f"baseline: {len(updated)} output image(s) before attach")
    journal.write(req.bridge, req.img, phase="prepared", baseline=updated)
    return None, updated


async def _checkpoint(req: JobRequest) -> JobOutcome | None:
    """Pause/Stop/Cancel act on the verified checkpoint, before anything is sent."""
    if _cancelled(req):
        return JobOutcome(CANCELLED, error="Cancelled by user")
    if getattr(req.bridge, "_pause_requested", False):
        _log(req, "⏸ paused at the verified checkpoint — attachment and prompt verified, NOT submitted", "warn")
        while getattr(req.bridge, "_pause_requested", False):
            await asyncio.sleep(PAUSE_POLL_SEC)
            if _cancelled(req):
                return JobOutcome(CANCELLED, error="Cancelled by user")
        _log(req, "▶ resumed from the verified checkpoint (no re-attach, no re-insert)")
    return None


async def _submit(req: JobRequest, baseline: list) -> tuple:
    """The guarded single Send click, then the correlated result (or honest doubt)."""
    budget = job_macro.generation_timeout_ms(req.bridge)
    _log(req, f"→ submit intent: one guarded click, generation timeout {budget}ms")
    kind, message, replies = await _stage(req, _inputs(req, "submit", StageFacts(baseline=baseline), budget=budget))
    clicks = job_replies.submit_count(replies.submit)
    did_submit, evidence = job_replies.submitted(replies)
    if not did_submit:
        reason = replies.guard_why or message or "no submit evidence"
        _log(req, f"⛔ not submitted: {reason}", "error")
        return _failed(req, f"not submitted: {reason}"), Submission(clicks, job_replies.MISSING)
    journal.write(req.bridge, req.img, phase="submitted", submit_clicks=clicks, evidence=evidence)
    _log(req, f"✅ Submitted — {evidence}", "success")
    if _cancelled(req):
        return _review(req, "cancelled after submit — the in-flight result is kept for review"), \
            Submission(clicks, job_replies.UNCERTAIN, reason="cancelled after submit")
    status, src, reason = job_replies.correlate(replies.result)
    if src:
        # record the correlated src at once: a crash before the download must
        # recover as "collect this result", never as "ask the page again"
        journal.write(req.bridge, req.img, src=src)
    return None, Submission(clicks, status, src=src, reason=reason)


def _result_outcome(req: JobRequest, sub: Submission) -> JobOutcome:
    """No usable result: name the cause, keep the evidence, never "completed"."""
    if sub.status == job_replies.UNCERTAIN:
        _log(req, f"⚠ generation uncertain: {sub.reason}", "warn")
        return _review(req, f"result uncertain: {sub.reason}")
    if sub.status == job_replies.AMBIGUOUS:
        _log(req, f"⚠ {sub.reason} — refusing to pick one", "warn")
        return _review(req, f"multiple candidate results: {sub.reason}")
    if sub.status == job_replies.REJECTED:
        return _review(req, f"no current-job result: {sub.reason}")
    if sub.clicks:
        return _review(req, "a Send click was recorded but the page shows no trace of this job")
    return _failed(req, f"no result: {sub.reason}")


async def _bytes_for(req: JobRequest, src: str) -> tuple:
    """(ok, data, note) — shared HTTPS fetch first, the page's own fetch second."""
    if str(src).startswith(("http://", "https://")):
        _log(req, f"⬇ download started: {src[:90]}")
        ok, data, note = await asyncio.to_thread(result.download, src)
        if ok:
            return True, data, note
        _log(req, f"⚠ direct download failed ({note}) — asking the page for its own bytes", "warn")
    else:
        _log(req, "⬇ the result is a page-local URL — fetching it through the page")
    kind, message, replies = await _stage(req, _inputs(req, "fetch", StageFacts(src=src)))
    ok, data, note = job_replies.bytes_from(replies.data)
    if not ok:
        return False, b"", f"{note} ({kind}: {message})"
    _log(req, f"⬇ the page delivered {note}")
    return True, data, note


async def _save(req: JobRequest, data: bytes, ext: str) -> JobOutcome:
    """Staging first, then the atomic final save — both named honestly on failure."""
    settings = _settings(req.bridge)
    final_path = result.plan_output(req.img, settings, ext=ext)
    ok, note = result.store_staging(final_path, data)
    if not ok:
        _log(req, f"❌ {note}", "error")
        return _failed(req, note)
    _log(req, f"💾 atomic save started: {final_path.name}")
    ok, note = result.finalize(final_path, data)
    if not ok:
        _log(req, f"❌ {note} (the staged bytes are kept for the next attempt)", "error")
        return _failed(req, note)
    req.img.output_path = str(final_path)
    journal.write(req.bridge, req.img, phase="saved", final_path=str(final_path))
    journal.clear(req.bridge, req.img)
    _log(req, f"✅ Saved {final_path.name} ({len(data)} bytes)", "success")
    return JobOutcome(COMPLETED, output_path=str(final_path))


async def _collect(req: JobRequest, sub: Submission) -> JobOutcome:
    """Correlated result → bytes → validation → staging → atomic save."""
    if sub.status != job_replies.READY or not sub.src:
        return _result_outcome(req, sub)
    _log(req, f"🔎 result correlated: {sub.reason} — {sub.src[:90]}", "success")
    ok, data, note = await _bytes_for(req, sub.src)
    if not ok:
        _log(req, f"❌ not downloadable: {note}", "error")
        return _failed(req, f"not downloadable: {note}")
    ok, ext, note = result.validate_bytes(data)
    if not ok:
        _log(req, f"❌ validation failed: {note}", "error")
        return _failed(req, f"validation failed: {note}")
    _log(req, f"✅ valid image: {note}", "success")
    journal.write(req.bridge, req.img, phase="downloaded", src=sub.src, ext=ext, bytes=len(data))
    return await _save(req, data, ext)


async def _probe_plan(req: JobRequest, ev):
    """A recorded submit without a result: ask the page, never resubmit."""
    _log(req, "recovery: a submit is recorded without a result — probing the page", "warn")
    kind, message, replies = await _stage(req, _inputs(req, "probe"))
    if not replies.answered:
        return recovery.Recovery(recovery.REVIEW, final_path=str(ev.final_path),
                                 note=f"the recovery probe answered nothing ({kind}: {message})")
    return recovery.after_probe(ev, {"result": replies.result}, job_replies.correlate)


async def _reconcile(req: JobRequest, plan) -> JobOutcome:
    """The output file is already there: mark it completed without touching the page."""
    ok, _ext, note = result.validate_bytes(Path(plan.final_path).read_bytes())
    if not ok:
        return _review(req, f"the existing output file is unusable ({note})")
    req.img.output_path = str(plan.final_path)
    journal.clear(req.bridge, req.img)
    _log(req, f"✅ output already on disk — reconciled {Path(plan.final_path).name} (no resubmit)", "success")
    return JobOutcome(COMPLETED, output_path=str(plan.final_path))


async def _resume_outcome(req: JobRequest, plan) -> JobOutcome | None:
    """Turn a recovery plan into an outcome, or None when a fresh attempt is safe."""
    if plan.action == recovery.DONE:
        return await _reconcile(req, plan)
    if plan.action == recovery.FINALIZE:
        ok, note = result.finalize(Path(plan.final_path), plan.data)
        if not ok:
            return _failed(req, note)
        req.img.output_path = str(plan.final_path)
        journal.clear(req.bridge, req.img)
        _log(req, f"✅ finished the staged download — Saved {Path(plan.final_path).name}", "success")
        return JobOutcome(COMPLETED, output_path=str(plan.final_path))
    if plan.action == recovery.COLLECT:
        _log(req, f"recovery: {plan.note}", "warn")
        ok, data, note = await _bytes_for(req, plan.src)
        if not ok:
            return _failed(req, f"not downloadable: {note}")
        valid, ext, note = result.validate_bytes(data)
        if not valid:
            return _failed(req, f"validation failed: {note}")
        return await _save(req, data, ext)
    if plan.action == recovery.REVIEW:
        return _review(req, f"recovery: {plan.note}")
    _log(req, f"recovery: {plan.note}")
    return None


async def _resume(req: JobRequest, final_path: Path) -> tuple:
    """Steps 16's evidence order: the files, then the journal, then the page."""
    data = journal.read(req.bridge, req.img)
    if data and not journal.belongs_to(data, req.img):
        data = {}
    evidence = recovery.Evidence(journal=data, final_path=final_path,
                                 source_path=Path(str(req.img.absolute_path)),
                                 settings=_settings(req.bridge))
    plan = recovery.plan(evidence)
    if plan.action == recovery.PROBE:
        plan = await _probe_plan(req, evidence)
    outcome = await _resume_outcome(req, plan)
    if outcome is not None:
        return data, outcome
    started = journal.write(req.bridge, req.img, phase="baseline", token=req.corr_id,
                            tab_id=req.page.tab_id, final_path=str(final_path),
                            attempts=journal.attempts(data) + 1, started_at=journal.now_iso())
    return started, None


async def run_image_job(req: JobRequest) -> JobOutcome:
    """One Firefox image job end to end — steps 14–19 in one place."""
    blocked = _preflight(req)
    if blocked is not None:
        return blocked
    if getattr(req.bridge, "_stop_after", False):
        _log(req, "stop-after-current requested — this job finishes, then no new claim")
    final_path = result.plan_output(req.img, _settings(req.bridge))
    data, resumed = await _resume(req, final_path)
    if resumed is not None:
        return resumed
    baseline = [str(s) for s in (data.get("baseline") or [])]
    _log(req, f"job {req.job_id} attempt {journal.attempts(data)} — "
              f"{Path(str(req.img.absolute_path)).name} on {_label(req)}")
    failure, baseline = await _prepare(req, baseline)
    if failure is not None:
        return failure
    failure = await _checkpoint(req)
    if failure is not None:
        return failure
    failure, sub = await _submit(req, baseline)
    if failure is not None:
        return failure
    return await _collect(req, sub)
