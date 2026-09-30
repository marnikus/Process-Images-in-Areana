"""StateProvider contract — one small owner per native state domain.

A provider owns capture / validate / migrate / apply for ITS native file
and format; the services never re-serialise feature state into a
unified model. Rollback is `apply()` of the pre-apply capture — every
provider's apply must therefore be idempotent per doc (task rule 4:
transactional inside each domain). No Qt, no app.ui imports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def config_dir(bridge) -> Path:
    """The live config directory (one home for meta, recovery, index and providers)."""
    return Path(getattr(bridge.config, "dir", "config"))


def read_live_json(path) -> tuple:
    """(doc, "") for a readable object or a missing file ({}); (None, cause) otherwise.

    RULE 4: a live file that exists but is unreadable, corrupt or not an object is
    BROKEN, never "empty" — capturing it as {} would let a later restore wipe the store.
    """
    if not path or not Path(path).exists():
        return {}, ""
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"live file {path.name} is unreadable: {exc}"
    if not isinstance(doc, dict):
        return None, f"live file {path.name} is not a JSON object"
    return doc, ""


def live_capture(path, empty_note: str = "") -> "CaptureResult":
    """CaptureResult for a one-file store read with `read_live_json`."""
    doc, cause = read_live_json(path)
    if cause:
        return CaptureResult(ok=False, notes=[cause])
    notes = [empty_note] if empty_note and not (path and Path(path).exists()) else []
    return CaptureResult(ok=True, doc=doc, notes=notes)


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


def object_doc(doc) -> str | None:
    """`'document is not an object'` for anything that is not a JSON object.

    The one shape check every domain's `validate` starts with (RULE 16.4 — it
    was re-derived in five providers).
    """
    return None if isinstance(doc, dict) else "document is not an object"


def members(doc: dict, **shapes) -> str | None:
    """`key must be a <type>` for the first key that is present with a wrong type.

    Absent keys are tolerated (a snapshot written by an older build simply has
    fewer keys); only a PRESENT key of the wrong type is an error.
    """
    for key, expected in shapes.items():
        if key in doc and not isinstance(doc[key], expected):
            return f"'{key}' must be a {expected.__name__}"
    return None


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
    # True = the snapshot is unusable without this domain, so a capture failure
    # refuses the save (unless the user allows a partial snapshot). False = a
    # failure degrades the save to `partial`, is listed in the report and the
    # log, and marks the domain excluded so a later restore skips it. See
    # `save._blocking` — this flag is read there and in `reports.save_report`.
    required = False
    restore_advice = ""       # what the user should do about an excluded domain

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

    def apply(self, bridge, doc) -> ApplyOutcome:
        """Stage + commit atomically for this domain; raises on failure."""
        raise NotImplementedError(f"{self.domain_id} cannot apply")

    def reconcile(self, bridge) -> list:
        """Post-restore derived/live recomputation notes (task rule 7)."""
        return []

    def _one_file(self, path) -> list:
        return [Path(path)] if path and Path(path).exists() else []
