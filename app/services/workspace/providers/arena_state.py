"""arena_state provider — `config/app_state.json` (urls, folder, prompt, settings, queue, jobs).

Capture is the live `AppState.to_dict()` (native format, orchestrator never
re-shapes it); apply parses through `AppState.from_dict` FIRST so a bad doc
fails before any live field moves, then swaps fields and persists through
the app's own atomic writer. Derived/live values (`run_state`, in-flight
jobs, `processing` images) are reconciled after restore, never trusted.
"""

from __future__ import annotations

from app.core.models import AppState
from app.core.persistence import save_state
from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider

SCHEMA_VERSION = "1.0.0"
_LIST_KEYS = ("urls", "images", "jobs")
_DICT_KEYS = ("prompt", "settings", "folder")
_SWAP_FIELDS = ("urls", "folder", "prompt", "settings", "images", "jobs",
                "progress", "run_state", "last_run")


def _list_error(doc: dict, key: str) -> str | None:
    value = doc.get(key)
    if not isinstance(value, list):
        return f"'{key}' must be a list"
    if any(not isinstance(row, dict) for row in value):
        return f"'{key}' rows must be objects"
    return None


def _shape_error(doc) -> str | None:
    """List/dict member shapes (checked before identity invariants)."""
    for key in _LIST_KEYS:
        err = _list_error(doc, key)
        if err:
            return err
    for key in _DICT_KEYS:
        if not isinstance(doc.get(key), dict):
            return f"'{key}' must be an object"
    return None


def _images_error(doc) -> str | None:
    """Image-row identity: unique, and always id + relative_path."""
    rows = doc.get("images", [])
    ids = [row.get("id") for row in rows]
    if len(ids) != len(set(ids)):
        return "duplicate image ids"
    if any(not row.get("id") or not row.get("relative_path") for row in rows):
        return "image rows need 'id' and 'relative_path'"
    return None


def semantic_error(doc) -> str | None:
    """The arena_state invariants (checked before anything is applied)."""
    if not isinstance(doc, dict):
        return "document is not an object"
    shape_problem = _shape_error(doc) or _images_error(doc)
    return shape_problem


def swap_state(state, candidate: AppState) -> None:
    """Commit the parsed candidate onto the live AppState (parsing already validated)."""
    for name in _SWAP_FIELDS:
        setattr(state, name, getattr(candidate, name))


class ArenaStateProvider(StateProvider):
    """Queue / URLs / folder / prompt / settings / jobs — the app's main state."""

    domain_id = "arena_state"
    display_name = "Queue, URLs, Folder, Prompt, Jobs"
    native_rel_path = "state/app_state.json"
    schema_version = SCHEMA_VERSION
    supported_migrations = (SCHEMA_VERSION,)
    dependencies = {"cooldowns": "optional"}
    sensitivity = "personal"   # absolute local paths
    required = True

    def live_paths(self, bridge) -> list:
        return self._one_file(bridge.state_path)

    def capture(self, bridge) -> CaptureResult:
        return CaptureResult(ok=True, doc=bridge.state.to_dict())

    def validate(self, doc) -> str | None:
        return semantic_error(doc)

    def plan(self, bridge, doc) -> str:
        images = doc.get("images", []) if isinstance(doc, dict) else []
        urls = doc.get("urls", []) if isinstance(doc, dict) else []
        return f"{len(urls)} URL row(s), {len(images)} queue row(s)"

    def apply(self, bridge, doc) -> ApplyOutcome:
        candidate = AppState.from_dict(dict(doc))
        swap_state(bridge.state, candidate)
        save_state(bridge.state, bridge.state_path)
        return ApplyOutcome(ok=True)

    def reconcile(self, bridge) -> list:
        from app.core.persistence import _handle_interrupted
        notes = []
        interrupted = _handle_interrupted(bridge.state)
        if interrupted:
            notes.append(f"{interrupted} in-flight job(s) marked interrupted")
        if bridge.state.run_state != "idle":
            from app.services.live.supervisor import set_run_state
            set_run_state(bridge, "idle")
            notes.append("run_state forced to idle — a saved run is never revived")
        bridge.state.recalculate_progress()
        bridge._save_arena()
        return notes
