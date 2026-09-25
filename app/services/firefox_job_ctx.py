"""Firefox image job — the shared context every phase uses (design §3/§17, 2026-09-25).

`FfJob` is the job's value object (RULE 16 parameter budget: phases take ONE
argument). `run_macro` runs one phase macro to its verdict and returns the
job's parsed replies; it is uncancellable by design — a started macro always
finishes (the OS dialog is never abandoned, the lock never released early) and
a cancel is re-raised afterwards. Events use Chrome's `JobAction` with Chrome's
block ids, so the Action Blocks window shows a Firefox job like a Chrome one;
every log line carries the lane marker + the correlation prefix `🦊 [corr]`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.browser.uivision import job_macros as uv_job
from app.services import firefox_lane as fl
from app.services.captcha.policy import captcha_in_scope
from app.services.run_state import JobAction

JOBS_DIR = "firefox_jobs"


class JobFailure(Exception):
    """A job that must end now; `review=True` = the outcome is uncertain (never resubmit)."""

    def __init__(self, message: str, review: bool = False):
        super().__init__(message)
        self.review = review


class JobCancelled(Exception):
    """The user's Cancel seen at a checkpoint (the task itself was not cancelled)."""


def cancel_requested(bridge) -> bool:
    return bool(getattr(bridge, "_cancel_requested", False))


@dataclass
class FfJob:
    """One Firefox image job: who, what, and the evidence gathered so far."""

    bridge: Any
    pool: Any
    page: Any
    img: Any
    corr: str
    prompt: str
    journal: Any
    staged: str = ""
    baseline: dict = field(default_factory=dict)
    err_base: str = ""
    prompt_sha: str = ""
    src: str = ""
    uncertain: bool = False
    review: bool = False
    skip_reset: bool = False

    @property
    def tab_id(self) -> str:
        return self.page.tab_id

    @property
    def staged_name(self) -> str:
        return Path(self.staged).name if self.staged else ""


def log(job: FfJob, message: str, level: str = "info") -> None:
    try:
        job.bridge._log(f"🦊 [{job.corr}] {message}", level)
    except Exception:
        pass


def emit(job: FfJob, block: str, status: str, message: str) -> None:
    """Chrome's block event + the matching log line (RULE 2)."""
    try:
        job.bridge._emit_job_action_status(JobAction(job.corr, block, status, message))
    except Exception:
        pass
    level = {"failed": "error", "success": "info"}.get(status, "info")
    log(job, f"{block}: {message}", level)


def in_scope(job: FfJob) -> bool:
    """Captcha work only while the Watcher is ON (RULE 20)."""
    return captcha_in_scope(job.bridge)


def timeout_s(job: FfJob, key: str, default: int) -> int:
    """`settings.timeouts[key]` — the same knobs the Chrome lane reads."""
    try:
        return int(job.bridge.state.settings.timeouts.get(key, default))
    except Exception:
        return default


def settings_of(job: FfJob):
    return getattr(getattr(job.bridge, "state", None), "settings", None)


def config_dir(bridge) -> Path:
    """The app's config folder (the journal, uploads and job folders live under it)."""
    directory = getattr(getattr(bridge, "config", None), "dir", None)
    return Path(directory) if isinstance(directory, (str, Path)) else Path(".")


def job_dir(job: FfJob) -> Path:
    """`<config>/firefox_jobs/<corr>/` — the staged download lives here."""
    return config_dir(job.bridge) / JOBS_DIR / job.corr


def mark_pool(job: FfJob, kind: str) -> None:
    """Chrome's pool calls: `busy` / `generation` / `captcha` + one pool push."""
    try:
        if kind == "busy":
            job.pool.mark_busy(job.tab_id, job.corr)
        else:
            job.pool.mark_waiting(job.tab_id, kind)
        job.bridge._emit_pool_status()
    except Exception:
        pass


async def complete(coro):
    """Await `coro` to its end even when cancelled; re-raise the cancel afterwards."""
    task = asyncio.ensure_future(coro)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if not task.done():
            await asyncio.wait({task})
        raise


async def run_macro(job: FfJob, phase, required: bool = True) -> dict:
    """One phase macro → {phase: data} replies of THIS job; no answer = failure when required."""
    kind, message, lines = await complete(fl.run_phase(job.bridge, job.page, phase, job.corr))
    replies = uv_job.parse_replies(lines, job.corr)
    if not replies and required:
        raise JobFailure(f"Ui.Vision {kind}: {message or 'no answer'} ({phase.phase})")
    if kind != "ok":
        log(job, f"{phase.phase} macro ended {kind}: {message}", "warn")
    _raise_loader_error(replies)
    return replies


def _raise_loader_error(replies: dict) -> None:
    """The loader's own catch (`{ok: false, error}` only) = the page refused our script (e.g. CSP)."""
    for phase, data in replies.items():
        if isinstance(data, dict) and set(data) == {"ok", "error"} and not data["ok"]:
            raise JobFailure(f"page script failed in {phase}: {data['error']}")
