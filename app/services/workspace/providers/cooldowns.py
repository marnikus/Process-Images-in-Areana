"""cooldowns provider — `config/cooldowns.json` (timers, per-URL job stats, aliases).

The native file is the source of truth (written atomically on every pool
push); capture reads it, apply rewrites it through the same atomic writer.
Expired timers are dropped on the next load by the store itself — wall
clocks are derived/live state, never trusted blindly (task rule 7).
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import load_json, save_json_atomic
from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider

_SECTIONS = ("version", "entries", "stats", "aliases")


def cooldown_file(bridge) -> Path:
    from app.services.run_state import cooldowns_path
    return Path(cooldowns_path(bridge))


def read_live(path: Path) -> dict:
    """One retry on a transient read miss (the file is replaced on every pool push)."""
    if not Path(path).exists():
        return {}
    try:
        return load_json(path, {})
    except OSError:
        return load_json(path, {})


def sections_error(doc) -> str | None:
    if not isinstance(doc, dict):
        return "document is not an object"
    for key in ("entries", "stats", "aliases"):
        if key in doc and not isinstance(doc[key], dict):
            return f"'{key}' must be an object"
    return None


class CooldownsProvider(StateProvider):
    """Wall-clock cooldown timers + job counters + readable tab aliases."""

    domain_id = "cooldowns"
    display_name = "Cooldowns & Tab Aliases"
    native_rel_path = "state/cooldowns.json"
    schema_version = "1"
    sensitivity = "personal"   # aliases carry account e-mails

    def live_paths(self, bridge) -> list:
        return self._one_file(cooldown_file(bridge))

    def capture(self, bridge) -> CaptureResult:
        doc = read_live(cooldown_file(bridge))
        notes = [] if doc else ["no live cooldown file — captured empty"]
        return CaptureResult(ok=True, doc=doc, notes=notes)

    def validate(self, doc) -> str | None:
        return sections_error(doc)

    def plan(self, bridge, doc) -> str:
        entries = doc.get("entries", {}) if isinstance(doc, dict) else {}
        return f"{len(entries)} cooldown timer(s), {len(doc.get('aliases', {}) if isinstance(doc, dict) else {})} alias(es)"

    def apply(self, bridge, doc) -> ApplyOutcome:
        clean = {key: doc[key] for key in _SECTIONS if key in doc}
        save_json_atomic(cooldown_file(bridge), clean)
        return ApplyOutcome(ok=True)
