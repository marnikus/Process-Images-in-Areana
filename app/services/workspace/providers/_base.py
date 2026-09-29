"""Shared base for JSON-file providers — reduces duplication (S6).

A provider that owns one JSON file can inherit `JsonFileProvider` and only
override `file_path()` + `validate()`. Capture and apply are the common
`live_capture` / `save_json_atomic` pair used by captcha_stats, job_history,
cooldowns. Providers that use ConfigManager stores (preset_stores, session)
keep their own bases.
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import save_json_atomic
from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider, live_capture


class JsonFileProvider(StateProvider):
    """One JSON file on disk — the common live_paths/capture/apply trio."""

    empty_note: str = ""

    def file_path(self, bridge) -> Path:
        raise NotImplementedError(f"{self.domain_id} must define file_path()")

    def live_paths(self, bridge) -> list:
        return self._one_file(self.file_path(bridge))

    def capture(self, bridge) -> CaptureResult:
        return live_capture(self.file_path(bridge), self.empty_note)

    def apply(self, bridge, doc) -> ApplyOutcome:
        save_json_atomic(self.file_path(bridge), doc)
        return ApplyOutcome(ok=True)
