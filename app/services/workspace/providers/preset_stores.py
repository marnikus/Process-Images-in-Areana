"""Preset-store providers — `window_presets.json` and `arena_presets.json`.

Both stores already keep deep-copied, section-validated data; the provider
exports `all_data()` verbatim and applies through a new `replace_all()`
(public, validated — no private-state poking). Individual preset docs stay
in their native shape; grid payloads inside presets are validated at
preset-load time exactly as today (behavior-preservation, task rule 2).
"""

from __future__ import annotations

import copy

from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider


class _StoreProvider(StateProvider):
    """Shared base for the two ConfigManager preset stores."""

    store_attr = ""
    section = ""

    def _store(self, bridge):
        return getattr(bridge.config, self.store_attr)

    def live_paths(self, bridge) -> list:
        return self._one_file(self._store(bridge).path)

    def capture(self, bridge) -> CaptureResult:
        return CaptureResult(ok=True, doc=self._store(bridge).all_data())

    def validate(self, doc) -> str | None:
        if not isinstance(doc, dict):
            return "document is not an object"
        section = doc.get(self.section)
        expected = list if self.section == "url_presets" else dict
        if not isinstance(section, expected):
            return f"'{self.section}' must be a {expected.__name__}"
        return None

    def apply(self, bridge, doc) -> ApplyOutcome:
        self._store(bridge).replace_all(copy.deepcopy(doc))
        return ApplyOutcome(ok=True)

    def plan(self, bridge, doc) -> str:
        section = doc.get(self.section) if isinstance(doc, dict) else None
        count = len(section) if hasattr(section, "__len__") else 0
        return f"{count} preset(s)"


class WindowPresetsProvider(_StoreProvider):
    """Window layout presets (grid + window_states docs with preview/confirm/apply)."""

    domain_id = "window_presets"
    display_name = "Window Layout Presets"
    native_rel_path = "state/window_presets.json"
    schema_version = "1"
    store_attr = "window_presets"
    section = "window_presets"


class ArenaPresetsProvider(_StoreProvider):
    """Arena/feature presets (url, prompt, settings, arena preset sections)."""

    domain_id = "arena_presets"
    display_name = "Arena & Feature Presets"
    native_rel_path = "state/arena_presets.json"
    schema_version = "1"
    store_attr = "presets"
    section = "arena_presets"

    def validate(self, doc) -> str | None:
        base = super().validate(doc)
        if base:
            return base
        for key in ("url_presets", "prompt_presets", "settings_presets"):
            value = doc.get(key)
            want = list if key == "url_presets" else dict
            if not isinstance(value, want):
                return f"'{key}' must be a {want.__name__}"
        return None


def _unused(exc: WorkspaceError) -> None:  # noqa: ARG001 — keeps the import meaningful for re-exports
    raise exc
