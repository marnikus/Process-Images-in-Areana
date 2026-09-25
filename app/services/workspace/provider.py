"""StateProvider contract — one small owner per native state domain.

A provider owns capture / validate / migrate / apply for ITS native file
and format; the coordinator never re-serialises feature state into a
unified model. Rollback is `apply()` of the pre-apply capture — every
provider's apply must therefore be idempotent per doc (task rule 4:
transactional inside each domain). No Qt, no app.ui imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaptureResult:
    """One coherent capture at the snapshot boundary."""
    ok: bool
    doc: object = None
    notes: list = field(default_factory=list)
    excluded: bool = False
    excluded_reason: str = ""


@dataclass
class ApplyOutcome:
    ok: bool
    notes: list = field(default_factory=list)


class StateProvider:
    """Base contract; subclasses override what their domain owns.

    Class attributes are the manifest metadata; methods are the lifecycle.
    `validate` returns a semantic error string or None; `migrate` is pure
    and never rewrites the snapshot on disk (task rule: migrations pure).
    """

    domain_id = ""
    display_name = ""
    native_rel_path = ""      # '' for policy-excluded (secret/opt-out) domains
    schema_version = "1"
    supported_migrations: tuple = ("1",)
    dependencies: dict = {}   # {domain_id: "strict" | "optional"}
    sensitivity = "public"    # public | personal | secret
    required = False          # save aborts (unless allow_partial) when a required domain fails

    def live_paths(self, bridge) -> list:
        """Files to copy into the recovery backup before this domain applies."""
        return []

    def capture(self, bridge) -> CaptureResult:
        raise NotImplementedError(f"{self.domain_id} cannot capture")

    def validate(self, doc) -> str | None:
        """Semantic invariants over the parsed doc (schema version is checked separately)."""
        return None

    def migrate(self, doc, from_version: str):
        """Pure old→current conversion; returns (doc, note)."""
        return doc, ""

    def plan(self, bridge, doc) -> str:
        """One-line preview of what will change (shown before restore)."""
        return self.display_name

    def apply(self, bridge, doc) -> ApplyOutcome:
        """Stage + commit atomically for this domain; raises on failure."""
        raise NotImplementedError(f"{self.domain_id} cannot apply")

    def reconcile(self, bridge) -> list:
        """Post-restore derived/live recomputation notes (task rule 7)."""
        return []

    def _one_file(self, path) -> list:
        return [Path(path)] if path and Path(path).exists() else []
