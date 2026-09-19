"""Fail-open lifecycle facade for per-tab captcha recordings."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .comparison import RecordingComparison
from .reader import EvidenceReader
from .recorder import CaptchaRecorder
from .store import RecordingStore, recording_enabled, save_recording_enabled


def _drop_active(active: dict[str, CaptchaRecorder], recorder: CaptchaRecorder) -> None:
    """Forget a finished recorder by identity (one tab can hold only one)."""
    for tab_id, held in tuple(active.items()):
        if held is recorder:
            active.pop(tab_id, None)


class RecordingManager:
    """Own active recorders and expose summaries/labels to the UI."""

    def __init__(self, config_dir: str, log: Optional[Callable[[str, str], None]] = None):
        self.store = RecordingStore(config_dir)
        self.reader = EvidenceReader(self.store.root)
        self.comparison = RecordingComparison()
        self.log = log or (lambda message, level="info": None)
        self._active: dict[str, CaptchaRecorder] = {}

    async def start(self, ctrl: Any, encounter: dict[str, Any]) -> Optional[CaptchaRecorder]:
        if not recording_enabled(self.store.root):
            return None
        tab_id = str(encounter.get("tab", ""))
        cdp = getattr(ctrl, "cdp", None)
        if tab_id in self._active or not callable(getattr(cdp, "send", None)):
            return None
        try:
            recorder = CaptchaRecorder(self.store, ctrl, encounter)
            await recorder.start()
            self._active[tab_id] = recorder
            self.log(f"🎞 Captcha recording {recorder.session_id} started", "info")
            return recorder
        except Exception as exc:
            self.log(f"Captcha recording start skipped: {exc}", "warn")
            return None

    async def finish(self, recorder: Optional[CaptchaRecorder], outcome: Any, report: dict | None = None) -> None:
        if recorder is None:
            return
        try:
            manifest = await recorder.finish(outcome, report)
            self.log(f"🎞 Captcha recording {recorder.session_id} finished: "
                     f"{manifest.get('outcome', '?')}", "info")
        except Exception as exc:
            self.log(f"Captcha recording finish failed: {exc}", "warn")
        finally:
            _drop_active(self._active, recorder)

    async def note(self, tab_id: str, phase: str, outcome: Any) -> None:
        recorder = self._active.get(tab_id)
        if recorder is None:
            return
        try:
            await recorder.note_outcome(phase, outcome)
        except Exception as exc:
            self.log(f"Captcha recording milestone skipped: {exc}", "warn")

    async def abort(self, recorder: Optional[CaptchaRecorder], reason: str) -> None:
        if recorder is None:
            return
        try:
            await recorder.abort(reason)
        except Exception as exc:
            self.log(f"Captcha recording abort failed: {exc}", "warn")
        finally:
            _drop_active(self._active, recorder)

    def list_sessions(self, limit: int = 1000) -> list[dict[str, Any]]:
        return self.store.list_sessions(limit)

    def count_sessions(self) -> int:
        return self.store.count_sessions()

    def delete_session(self, session_id: str) -> dict[str, Any]:
        return self.store.delete_session(session_id)

    def set_label(self, session_id: str, label: str) -> dict[str, Any]:
        return self.store.set_label(session_id, label)

    def set_labels(self, session_id: str, actor: str, result: str) -> dict[str, Any]:
        return self.store.set_labels(session_id, actor, result)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.reader.details(session_id)

    def session_folder(self, session_id: str) -> str:
        return str(self.reader.folder(session_id))

    def is_enabled(self) -> bool:
        return recording_enabled(self.store.root)

    def set_enabled(self, enabled: bool) -> bool:
        save_recording_enabled(self.store.root, enabled)
        return bool(enabled)

    def compare_sessions(self, left_id: str, right_id: str) -> dict[str, Any]:
        """Side-by-side evidence report for two finished sessions (window #15)."""
        return self.comparison.compare(self.get_session(left_id), self.get_session(right_id))
