"""Workspace run contexts — the value objects one save/restore execution shares.

One concept, one home: `SaveRequest` is what the UI asks for, `SaveRun`/
`RestoreRun` are the declared fields the save and restore algorithms pass
through their helpers (no untyped run dicts, no output-via-input mutation).
`save.py` re-exports `SaveRequest`/`SaveRun` so the public import surface
stays put. No Qt, no app.ui imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SaveRequest:
    """Parameters of one workspace save (param object — keeps signatures ≤4)."""
    name: str
    description: str = ""
    selected: list | None = None
    allow_partial: bool = False
    base_dir: str = ""


@dataclass
class SaveRun:
    """Context of one save execution — the shared fields, declared once.

    `snapshot_id` is computed once at run start (from the UTC stamp + name)
    and shared by the report and the manifest — one id, one computation.
    """
    bridge: object
    request: SaveRequest
    target: Path
    started: str
    snapshot_id: str


@dataclass
class RestoreRun:
    """Context of one restore execution — the shared fields, declared once."""
    bridge: object
    manifest: dict
    files: dict
    failed: set
