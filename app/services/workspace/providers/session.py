"""session.json providers — one physical file, two key-ownership domains.

`session_settings` owns every default-session key except the grid trio;
`grid_window` owns exactly `grid_layout` / `window_states` /
`window_geometry` (design §C.4 shared-file contract). The workspace
exports ONE native `state/session.json`; restore applies only the
selected domain's keys and commits the file once per domain atomically.
Invalid grid data is skipped with the current layout retained (RULE 13);
unknown window ids are a semantic error, never silently healed.
"""

from __future__ import annotations

from app.core.layout_service import canonical_grid_payload, leaf_ids
from app.core.window_catalog import GRID_VERSION, LEGACY_WINDOW_IDS, WINDOW_IDS
from app.persistence.json_store import load_json, save_json_atomic
from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider

GRID_KEYS = ("grid_layout", "window_states", "window_geometry")


def settings_keys() -> tuple:
    """Every default session key NOT owned by grid_window (one home: config_manager defaults)."""
    from app.persistence.config_manager import DEFAULT_SESSION
    return tuple(key for key in DEFAULT_SESSION if key not in GRID_KEYS)


def grid_error(doc) -> str | None:
    """Semantic validation for the grid trio.

    The canonical pipeline IS the unknown-panel policy: it validates the
    tree shape, migrates legacy window ids and appends missing leaves, and
    refuses unknown ids with a hard error (RULE 13 — invalid grid is
    skipped at restore, never defaulted). Here we only add the window
    states / geometry invariants on top.
    """
    raw = doc.get("grid_layout")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        return "grid_layout must be a non-empty canonical JSON string"
    _, err = canonical_grid_payload(raw)
    if err:
        return f"invalid grid: {err}"
    return _states_error(doc)


def _states_error(doc) -> str | None:
    states = doc.get("window_states")
    if states is None:
        return None
    if not isinstance(states, dict):
        return "window_states must be an object"
    for key in ("closed", "minimized"):
        value = states.get(key, [])
        if not isinstance(value, list):
            return f"window_states.{key} must be a list"
    return None


def _geometry_error(doc) -> str | None:
    geometry = doc.get("window_geometry")
    if geometry is None:
        return None
    if not isinstance(geometry, dict):
        return "window_geometry must be an object"
    for key in ("x", "y", "width", "height"):
        value = geometry.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return f"window_geometry.{key} must be an int"
    if geometry.get("width", 0) <= 0 or geometry.get("height", 0) <= 0:
        return "window_geometry width/height must be positive"
    return None


def filter_window_states(raw) -> dict:
    """Closed/minimized restricted to known window ids (same rule as the live slot)."""
    states = raw if isinstance(raw, dict) else {}
    known = set(WINDOW_IDS)

    def _kept(ids):
        return [i for i in ids if isinstance(i, str) and i in known]

    closed = _kept(states.get("closed", []))
    minimized = [i for i in _kept(states.get("minimized", [])) if i not in closed]
    return {"closed": closed, "minimized": minimized}


class _SessionDomainProvider(StateProvider):
    """Shared base: both domains read/commit `session.json` through SessionStore."""

    def _store(self, bridge):
        return bridge.config.session

    def live_paths(self, bridge) -> list:
        return self._one_file(self._store(bridge).path)

    def _keys(self) -> tuple:
        raise NotImplementedError

    def capture(self, bridge) -> CaptureResult:
        doc = self._store(bridge).data()
        return CaptureResult(ok=True, doc={key: doc.get(key) for key in self._keys()})

    def validate(self, doc) -> str | None:
        if not isinstance(doc, dict):
            return "document is not an object"
        return None

    def _prepared(self, key: str, value):
        return value

    def apply(self, bridge, doc) -> ApplyOutcome:
        store = self._store(bridge)
        merged = store.data()
        for key in self._keys():
            if key in doc:
                merged[key] = self._prepared(key, doc[key])
        save_json_atomic(store.path, merged)
        store.load()
        return ApplyOutcome(ok=True)


class SessionSettingsProvider(_SessionDomainProvider):
    """Session & settings keys of session.json (watcher/cooldown/cdp/browser config…)."""

    domain_id = "session_settings"
    display_name = "Session & Settings"
    native_rel_path = "state/session.json"
    schema_version = "1"
    sensitivity = "personal"
    required = True

    def _keys(self) -> tuple:
        return settings_keys()

    def plan(self, bridge, doc) -> str:
        incoming = sorted(key for key in self._keys() if key in doc)
        return f"{len(incoming)} session key(s): {', '.join(incoming[:6])}…"


class GridWindowProvider(_SessionDomainProvider):
    """Grid layout + window states + geometry — the sash-grid workspace shape."""

    domain_id = "grid_window"
    display_name = "Grid & Window Layout"
    native_rel_path = "state/session.json"
    schema_version = str(GRID_VERSION)
    supported_migrations = tuple(str(v) for v in range(4, GRID_VERSION + 1))
    sensitivity = "public"

    def _keys(self) -> tuple:
        return GRID_KEYS

    def capture(self, bridge) -> CaptureResult:
        result = super().capture(bridge)
        result.notes = ["shared file with session_settings (one state/session.json)"]
        return result

    def validate(self, doc) -> str | None:
        base = super().validate(doc)
        if base:
            return base
        for checker in (grid_error, _geometry_error):
            err = checker(doc)
            if err:
                return err
        return None

    def migrate(self, doc, from_version: str):
        """Older GRID_VERSION payloads already migrate inside canonical_grid_payload."""
        return doc, "" if from_version == self.schema_version else \
            f"grid schema {from_version} → {self.schema_version} (canonical pipeline)"

    def _prepared(self, key: str, value):
        if key == "grid_layout" and isinstance(value, str) and value:
            payload, _err = canonical_grid_payload(value)
            return payload or value
        if key == "window_states":
            return filter_window_states(value)
        return value

    def plan(self, bridge, doc) -> str:
        return "grid layout, window states and geometry (screen clamp on apply)"

    def reconcile(self, bridge) -> list:
        return ["geometry may need clamping to this machine's screen"]
