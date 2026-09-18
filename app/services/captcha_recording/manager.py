"""Fail-open lifecycle facade for per-tab captcha recordings.

One recorder per tab, keyed by the tab id; the catalog (list/label/compare/
delete) is exposed as `manager.catalog` so this class stays inside the RULE 16
method budget and reads as one responsibility: start, stamp, resolve, join.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .catalog import RecordingCatalog
from .recorder import CaptchaRecorder
from .store import RecordingStore


class RecordingManager:
    """Own active recorders and resolve the later job verdict onto them."""

    def __init__(self, config_dir: str, log: Optional[Callable[[str, str], None]] = None):
        self.store = RecordingStore(config_dir)
        self.log = log or (lambda message, level="info": None)
        self.catalog = RecordingCatalog(self.store, active_ids=self._active_session_ids)
        self._active: dict[str, CaptchaRecorder] = {}
        self._by_eid: dict[str, str] = {}

    async def start(self, ctrl: Any, encounter: dict[str, Any]) -> Optional[CaptchaRecorder]:
        """Open one recording for this tab; None means "nothing was recorded"."""
        tab_id = str(encounter.get("tab", ""))
        cdp = getattr(ctrl, "cdp", None)
        if tab_id in self._active:
            self.log(f"🎞 Captcha recording skipped — tab {tab_id[:12]} is already recording", "warn")
            return None
        if not callable(getattr(cdp, "evaluate", None)):
            self.log("Captcha recording skipped — no CDP evaluate path", "warn")
            return None
        try:
            recorder = CaptchaRecorder(self.store, ctrl, encounter)
            await recorder.start()
        except Exception as exc:
            self.log(f"Captcha recording start skipped: {exc}", "warn")
            return None
        self._active[tab_id] = recorder
        self._index(encounter, recorder)
        self.log(f"🎞 Captcha recording {recorder.session_id} started", "info")
        return recorder

    async def finish(self, recorder: Optional[CaptchaRecorder], outcome: Any,
                     report: Optional[dict[str, Any]] = None) -> None:
        if recorder is None:
            return
        try:
            manifest = await recorder.finish(outcome, report)
            self.log(f"🎞 Captcha recording {recorder.session_id} finished: "
                     f"{manifest.get('outcome', '?')} ({manifest.get('acceptance', 'none')})", "info")
        except Exception as exc:
            self.log(f"Captcha recording finish failed: {exc}", "warn")
        finally:
            self._drop(recorder)

    async def milestone(self, tab_id: str, phase: str,
                        data: Optional[dict[str, Any]] = None) -> None:
        """Stamp a live semantic edge; a missing session is not an error."""
        recorder = self._active.get(tab_id)
        if recorder is None:
            return
        try:
            await recorder.milestone(phase, data)
        except Exception as exc:
            self.log(f"Captcha recording milestone skipped: {exc}", "warn")

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

    def join_job(self, eid: str, line: dict[str, Any]) -> bool:
        """Resolve the image-job verdict onto its session once (RULE 4 join)."""
        session_id = self._by_eid.get(str(eid or "")) or self.store.find_by_eid(eid)
        if not session_id:
            return False
        try:
            manifest = self.store.apply_job(session_id, line)
            self.log(f"🎞 Captcha recording {session_id} job verdict: "
                     f"{manifest.get('job', '?')} (verified={manifest.get('verified')})", "info")
            return True
        except Exception as exc:
            self.log(f"Captcha recording job join failed: {exc}", "warn")
            return False

    def _index(self, encounter: dict[str, Any], recorder: CaptchaRecorder) -> None:
        eid = str(encounter.get("eid", ""))
        if eid:
            self._by_eid[eid] = recorder.session_id

    def _drop(self, recorder: CaptchaRecorder) -> None:
        for tab_id, active in tuple(self._active.items()):
            if active is recorder:
                self._active.pop(tab_id, None)

    def _active_session_ids(self) -> set[str]:
        return {str(recorder.session_id) for recorder in self._active.values()}
