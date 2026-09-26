"""Chrome job step tracker — milestones, confirmations, final / recycle verdict (2026-09-26).

docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md D-4.

`JobSteps` keeps the furthest `JobStatus` milestone the job reached. The block
stack is user-configurable, so progress is judged by *rank* (forward only), not
by `JOB_TRANSITIONS` adjacency — a disabled block must not produce a warning.
Every milestone and every confirmation (`job_flow.confirm`) is one `✔` / `✖` / `⚠`
line with the job's correlation prefix (RULE 2); the job ends with ONE summary
line and its verdict:

* `■ final ✅` — saved and confirmed on disk;
* `↻ recycle` — failed with attempts left: the live loop puts it back in the
  queue (the rule is `run_scope.in_live_scope`: `attempt_count` vs
  `settings.retries.max_attempts`, read through `live.feed.retry_cap`);
* `■ final` — failed with no attempts left, or stopped by the operator.

The tracker reports; the orchestrators stay the only writers of image status.
Imports: core + `live.feed` (services).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from app.core.enums import JobStatus as S
from app.services.live.feed import retry_cap

_ORDER = [s.value for s in (S.CREATED, S.BASELINE_CAPTURED, S.ATTACHING, S.ATTACHMENT_VERIFIED,
                            S.PROMPT_INSERTED, S.PROMPT_VERIFIED, S.SUBMITTED, S.WAITING_GENERATION,
                            S.OUTPUT_DETECTED, S.DOWNLOADING, S.VALIDATING, S.SAVING, S.COMPLETED)]
RANK = {status: i for i, status in enumerate(_ORDER)}

# block id → the milestone its success proves (unlisted blocks are helpers: highlight, pause, …)
BLOCK_STEP = {
    "OBSERVE_BASELINE": S.BASELINE_CAPTURED.value,
    "ATTACH_IMAGE": S.ATTACHMENT_VERIFIED.value,
    "VERIFY_ATTACHMENT": S.ATTACHMENT_VERIFIED.value,
    "INSERT_PROMPT": S.PROMPT_INSERTED.value,
    "VERIFY_PROMPT": S.PROMPT_VERIFIED.value,
    "SUBMIT": S.SUBMITTED.value,
    "WAIT_OUTPUT": S.OUTPUT_DETECTED.value,
    "DOWNLOAD": S.DOWNLOADING.value,
    "VALIDATE": S.VALIDATING.value,
    "SAVE": S.SAVING.value,
}
_NOTES = {
    S.BASELINE_CAPTURED.value: "outputs already on the page recorded",
    S.ATTACHMENT_VERIFIED.value: "image attached, preview visible",
    S.PROMPT_INSERTED.value: "prompt typed into the text area",
    S.PROMPT_VERIFIED.value: "text area holds the exact prompt",
    S.SUBMITTED.value: "send clicked",
    S.OUTPUT_DETECTED.value: "generation finished — the image with our JOB-ID is on the page",
    S.DOWNLOADING.value: "image bytes downloaded",
    S.VALIDATING.value: "bytes decode as an image",
    S.SAVING.value: "file written beside the source",
}

Say = Callable[[str, str], None]


@dataclass
class Outcome:
    """How the job ended, plus the inputs of the live loop's retry rule."""

    failed: bool
    error: str = ""
    cancelled: bool = False
    attempts: int = 0
    cap: int = 0
    selected: bool = True


@dataclass
class JobSteps:
    """The furthest milestone + an ordered ✔/✖ trail of steps and confirmations."""

    corr: str
    say: Say
    reached: str = S.CREATED.value
    trail: List[Tuple[str, bool]] = field(default_factory=list)
    done_blocks: set = field(default_factory=set)
    err_base: Optional[str] = None     # page-error corpus at job start (None = not read yet)
    failed_at: str = ""

    def log(self, msg: str, level: str = "info") -> None:
        try:
            self.say(f"[{self.corr}] {msg}", level)
        except Exception:
            pass

    def confirm(self, name: str, note: str) -> None:
        self.trail.append((name, True))
        self.log(f"✔ {name} — {note}", "success")

    def warn(self, name: str, note: str) -> None:
        self.log(f"⚠ {name} — {note}", "warn")

    def block_ok(self, block_id: str) -> None:
        self.done_blocks.add(block_id)
        step = BLOCK_STEP.get(block_id)
        if step and RANK[step] > RANK[self.reached]:
            self.reached = step
            self.trail.append((step, True))
            self.log(f"✔ {step} — {_NOTES.get(step, block_id)}", "success")

    def block_failed(self, block_id: str, err: str) -> None:
        step = BLOCK_STEP.get(block_id, block_id.lower() or "block")
        self.failed_at = step
        self.trail.append((step, False))
        self.log(f"✖ {step} — {err}", "warn")


def stage_note(reached: str) -> str:
    """What a failure at this point means for the image."""
    rank = RANK.get(reached, 0)
    if rank < RANK[S.SUBMITTED.value]:
        return "nothing was sent — safe to retry"
    if rank < RANK[S.OUTPUT_DETECTED.value]:
        return "sent, but no finished image — a retry sends a new job"
    return "image generated but not saved — a retry generates it again"


def verdict(reached: str, out: Outcome) -> str:
    """■ final or ↻ recycle, by the live loop's own retry rule."""
    if out.cancelled:
        return "■ stopped by the operator — the image stays failed; Start / Retry runs it again"
    if not out.failed:
        return "■ final ✅ saved and confirmed on disk"
    note = stage_note(reached)
    cap = f"{out.cap}" if out.cap > 0 else "∞"
    if out.selected and (out.cap <= 0 or out.attempts < out.cap):
        return f"↻ recycle: back in the queue (attempt {out.attempts}/{cap}) · {note}"
    return f"■ final: no attempts left ({out.attempts}/{cap}) · {note} — Retry runs it again"


def summary(steps: JobSteps, out: Outcome) -> str:
    """One line: the ✔/✖ trail, the end state and the verdict."""
    marks = " ".join(("✔" if ok else "✖") + name for name, ok in steps.trail)
    head = "COMPLETED" if not out.failed else f"FAILED at {steps.failed_at or steps.reached}: {out.error[:160]}"
    return f"🧭 Steps {marks} — {head} → {verdict(steps.reached, out)}"


# ---- glue over the runner's JobCtx (duck-typed: bridge, img, corr_id, tab_id, steps) ----

def steps_of(ctx) -> JobSteps:
    """The job's tracker (created on first use, so a handler called alone still reports)."""
    steps = getattr(ctx, "steps", None)
    if steps is None:
        steps = JobSteps(corr=str(getattr(ctx, "corr_id", "") or "job"), say=_say_of(ctx))
        ctx.steps = steps
    return steps


def _say_of(ctx) -> Say:
    bridge = getattr(ctx, "bridge", None)
    return getattr(bridge, "_log", None) or (lambda _m, _l="info": None)


def _outcome(ctx, failed: bool, error: str, cancelled: bool) -> Outcome:
    img = getattr(ctx, "img", None)
    return Outcome(failed=failed, error=str(error or ""), cancelled=cancelled,
                   attempts=int(getattr(img, "attempt_count", 0) or 0),
                   cap=retry_cap(ctx.bridge), selected=bool(getattr(img, "selected", True)))


def start_steps(ctx) -> JobSteps:
    """▶ one line per job start: image, tab, attempt (the tracker begins at `created`)."""
    ctx.steps = None
    steps = steps_of(ctx)
    out = _outcome(ctx, False, "", False)
    name = os.path.basename(str(getattr(ctx.img, "relative_path", "") or "image"))
    steps.trail.append((S.CREATED.value, True))
    steps.log(f"▶ Job started — {name} · tab {str(ctx.tab_id)[:8]} · attempt {out.attempts}/"
              f"{out.cap if out.cap > 0 else '∞'}", "info")
    return steps


def track_block(ctx, block_id: str, err: Optional[str]) -> None:
    """One block outcome into the trail (never raises)."""
    try:
        steps = steps_of(ctx)
        if err is None:
            steps.block_ok(block_id)
        else:
            steps.block_failed(block_id, err)
    except Exception:
        pass


def finish_steps(ctx, failed: bool, error: str, cancelled: bool) -> str:
    """The summary + verdict line (logged); returns it for tests / history."""
    steps = steps_of(ctx)
    out = _outcome(ctx, failed, error, cancelled)
    if not failed:
        steps.reached = S.COMPLETED.value
        steps.trail.append((S.COMPLETED.value, True))
    line = summary(steps, out)
    steps.log(line, "success" if not failed else ("warn" if "↻" in line else "error"))
    return line
