"""Fail-open lifecycle facade for per-tab captcha recordings."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .reader import EvidenceReader
from .recorder import CaptchaRecorder
from .store import RecordingStore


class RecordingManager:
    """Own active recorders and expose summaries/labels to the UI."""

    def __init__(self, config_dir: str, log: Optional[Callable[[str, str], None]] = None):
        self.store = RecordingStore(config_dir)
        self.reader = EvidenceReader(self.store.root)
        self.log = log or (lambda message, level="info": None)
        self._active: dict[str, CaptchaRecorder] = {}

    async def start(self, ctrl: Any, encounter: dict[str, Any]) -> Optional[CaptchaRecorder]:
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

    async def finish(self, recorder: Optional[CaptchaRecorder], outcome: Any) -> None:
        if recorder is None:
            return
        try:
            manifest = await recorder.finish(outcome)
            self.log(f"🎞 Captcha recording {recorder.session_id} finished: "
                     f"{manifest.get('outcome', '?')}", "info")
        except Exception as exc:
            self.log(f"Captcha recording finish failed: {exc}", "warn")
        finally:
            self._drop(recorder)

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
            self._drop(recorder)

    def list_sessions(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.list_sessions(limit)

    def set_label(self, session_id: str, label: str) -> dict[str, Any]:
        return self.store.set_label(session_id, "actor", label)

    def set_result_label(self, session_id: str, label: str) -> dict[str, Any]:
        return self.store.set_label(session_id, "result", label)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.reader.details(session_id)

    def session_folder(self, session_id: str) -> str:
        return str(self.reader.folder(session_id))

    def delete_session(self, session_id: str) -> None:
        """Delete one recording session and all its artifacts."""
        self.store.delete_session(session_id)

    def _drop(self, recorder: CaptchaRecorder) -> None:
        for tab_id, active in tuple(self._active.items()):
            if active is recorder:
                self._active.pop(tab_id, None)
