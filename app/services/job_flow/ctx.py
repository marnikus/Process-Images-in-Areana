"""The Chrome job's context + its two reporting helpers (split from single_job_runner, 2026-09-26).

`JobCtx` keeps handler params ≤ 4 (RULE 16). `emit_action` feeds the block
rows of the UI; `report` writes one job-log line with the correlation prefix
(RULE 2). Both never raise — a broken UI callback must not kill a job.
`single_job_runner` re-exports all three under their old names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.run_state import JobAction


@dataclass
class JobCtx:
    """Context to keep params ≤4."""

    bridge: Any
    ctrl: Any
    client: Any
    tab_id: str
    img: Any
    urls: List[Any]
    job_id: str
    corr_id: str
    final_prompt: str
    baseline: Dict[str, Any] = field(default_factory=dict)
    new_src: Optional[str] = None
    file_bytes: Optional[bytes] = None
    ctype: Optional[str] = None
    ext: Optional[str] = None
    old_srcs: List[str] = field(default_factory=list)
    steps: Any = None           # job_flow.steps.JobSteps — milestones + confirmations (2026-09-26)
    save_error: str = ""        # why the last save failed (shown in the job error)


def emit_action(ctx: JobCtx, block: Any, status: str, msg: str):
    """Emit action status."""
    try:
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, status, msg))
    except Exception:
        pass


def report(ctx: JobCtx, msg: str, level: str = "info"):
    """Job log line with the job correlation prefix (RULE 2)."""
    try:
        ctx.bridge._log(f"[{ctx.corr_id}] {msg}", level)
    except Exception:
        pass
