"""Workspace failure vocabulary — one stage list + one structured error.

Every save/restore problem is reported as a `WorkspaceError` carrying the
domain, the exact failure stage (one vocabulary — design §F matrix), a
concise technical cause (never secret material), optional expected/actual
values, and a recommended user action. Imports: stdlib only.
"""

from __future__ import annotations

STAGES = (
    "missing", "unsafe_path", "checksum", "parse", "schema", "semantic",
    "migration", "dependency", "capture", "apply", "reconcile", "rollback",
)

_RECOMMENDED = {
    "missing": "Restore this file from the snapshot, or skip this domain.",
    "unsafe_path": "Paths outside the workspace folder are refused.",
    "checksum": "The file changed after it was saved — re-save the workspace or skip this domain.",
    "parse": "The file is not valid JSON — skip this domain or fix the file by hand.",
    "schema": "Update the app to a build that reads this schema, or skip this domain.",
    "semantic": "Skip this domain; fix the saved file or re-save the workspace.",
    "migration": "Skip this domain — this build cannot migrate the saved version.",
    "dependency": "Restore the failed dependency first, then retry this domain.",
    "capture": "This domain could not be read for the snapshot — fix the cause or allow a partial snapshot.",
    "apply": "The previous values were kept. Retry the restore or report the error.",
    "reconcile": "State was restored but live recomputation failed — restart the app.",
    "rollback": "Open the recovery folder named in the report and restore by hand.",
}


def _short(value, limit: int = 120) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text[:limit]


class WorkspaceError(Exception):
    """One structured domain failure; `to_dict()` is the report row."""

    def __init__(self, domain_id: str, stage: str, cause: str,
                 evidence: tuple = None):
        """`evidence` is an optional (expected, actual) pair for checksum rows."""
        if stage not in STAGES:
            raise ValueError(f"unknown stage: {stage}")
        self.domain_id = domain_id
        self.stage = stage
        self.cause = str(cause)[:400]
        self.expected = evidence[0] if evidence else None
        self.actual = evidence[1] if evidence else None
        super().__init__(f"[{domain_id}] {stage}: {self.cause}")

    def recommended(self) -> str:
        """The one user-facing next step for this stage (never a silent default)."""
        return _RECOMMENDED[self.stage]

    def to_dict(self) -> dict:
        out = {"domain_id": self.domain_id, "stage": self.stage, "cause": self.cause,
               "recommended_action": self.recommended()}
        if self.expected is not None:
            out["expected"] = _short(self.expected)
        if self.actual is not None:
            out["actual"] = _short(self.actual)
        return out
