"""cooldowns provider — `config/cooldowns.json` (timers, per-URL job stats, aliases).

The native file is the source of truth (written atomically on every pool
push); capture reads it, apply rewrites it through the same atomic writer.
Expired timers are dropped on the next load by the store itself — wall
clocks are derived/live state, never trusted blindly (task rule 7).
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.cooldown_store import load_entries, load_stats, normalize_url
from app.persistence.json_store import load_json, save_json_atomic
from app.services.cooldown_service import restore_cooldown_entry, restore_page_stats
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

    def reconcile(self, bridge) -> list:
        """Re-apply restored timers into the LIVE pool (it re-persists the file).

        Without this the pool's next autosave would clobber the restored
        cooldowns.json with its stale in-memory timers. Only currently pooled
        tabs can be updated here; the rest pick the file up when they connect
        (restore_page_state reads it per tab).
        """
        pool = getattr(bridge, "_page_pool", None)
        if pool is None:
            return []
        entries, stats = load_entries(cooldown_file(bridge)), load_stats(cooldown_file(bridge))
        timers = self._reapply_timers(pool, entries)
        counters = self._reapply_stats(pool, stats)
        notes = []
        if timers or counters:
            notes.append(f"cooldowns: re-applied {timers} timer(s), {counters} counter(s) "
                         "into the live pool")
        return notes

    def _reapply_timers(self, pool, entries: dict) -> int:
        applied = 0
        for tab_id, entry in entries.items():
            try:
                applied += 1 if restore_cooldown_entry(pool, tab_id, entry) else 0
            except Exception:
                continue
        return applied

    def _reapply_stats(self, pool, stats: dict) -> int:
        applied = 0
        for tab_id, page in list(getattr(pool, "_pages", {}).items()):
            url = normalize_url(getattr(page, "url", "") or "")
            row = stats.get(url)
            if not row:
                continue
            try:
                applied += 1 if restore_page_stats(pool, tab_id, url, row) >= 0 else 0
            except Exception:
                continue
        return applied
