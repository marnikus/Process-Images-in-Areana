"""Session-recordings panel — the 9 WebChannel slots of window 15's listener.

The session-recording feature (`app/services/recording/`, `app/browser/recording_probes.py`)
keeps its bridge slots on the Bridge QObject: QWebChannel drops calls whose slot is
missing, silently. They were added to the pre-split bridge monolith; the split
(W1.6) and the merge with `main` lost them, so this mixin owns them again.

Slots stay thin: parse JSON -> delegate to `app.services.recording.payloads` ->
JSON. The service is created lazily and lives under `logs/recordings/`; a failing
import or store degrades to {"ok": false, "error": ...}, never to a raised slot.
"""

from __future__ import annotations

import json
from typing import Any

from app.ui.qt_compat import Slot

RECORDING_ROOT = "logs/recordings"


def _loads(payload_json: str) -> dict:
    data = json.loads(payload_json or "{}")
    return data if isinstance(data, dict) else {}


def _reply(build) -> str:
    """Run one payload builder, returning its JSON or an error reply."""
    try:
        return json.dumps(build(), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


class RecordingSessionsMixin:
    """Slots for listing, inspecting, labelling and deleting session recordings."""

    def _recording_service(self) -> Any:
        """Lazy RecordingService; sessions live under logs/recordings/."""
        svc = getattr(self, "_recording_service_obj", None)
        if svc is None:
            from app.services.recording.recorder import RecordingService
            svc = self._recording_service_obj = RecordingService(RECORDING_ROOT, self._log)
        return svc

    @Slot(result=str)
    def get_recordings_list(self) -> str:
        def build() -> dict:
            from app.services.recording import payloads
            return payloads.list_payload(self._recording_service())
        return _reply(build)

    @Slot(str, result=str)
    def get_recording_detail(self, payload_json: str) -> str:
        def build() -> dict:
            from app.services.recording import payloads
            data = _loads(payload_json)
            svc = self._recording_service()
            return payloads.detail_payload(svc.store, str(data.get("session_id", "")),
                                           int(data.get("event_limit", 400)))
        return _reply(build)

    @Slot(str, result=str)
    def get_recording_snapshot(self, payload_json: str) -> str:
        def build() -> dict:
            from app.services.recording import payloads
            data = _loads(payload_json)
            svc = self._recording_service()
            return payloads.snapshot_payload(svc.store, str(data.get("session_id", "")),
                                             str(data.get("name", "")))
        return _reply(build)

    @Slot(str, result=str)
    def get_recording_diff(self, payload_json: str) -> str:
        def build() -> dict:
            from app.services.recording import payloads
            return payloads.diff_payload(self._recording_service().store, _loads(payload_json))
        return _reply(build)

    @Slot(str, result=str)
    def set_recording_label(self, payload_json: str) -> str:
        def build() -> dict:
            from app.services.recording import payloads
            data = _loads(payload_json)
            result = payloads.label_payload(self._recording_service().store,
                                            str(data.get("session_id", "")),
                                            str(data.get("label", "")))
            self._log(f"🎬 recording label {'set' if result.get('ok') else 'rejected'} "
                      f"({result.get('label', result.get('error'))})", "info")
            return result
        return _reply(build)

    @Slot(str, result=str)
    def delete_recording(self, payload_json: str) -> str:
        def build() -> dict:
            from app.services.recording import payloads
            data = _loads(payload_json)
            result = payloads.delete_payload(self._recording_service(),
                                             str(data.get("session_id", "")))
            if result.get("ok"):
                self._log("🎬 recording deleted", "info")
            return result
        return _reply(build)

    @Slot(str, result=str)
    def set_recording_settings(self, payload_json: str) -> str:
        def build() -> dict:
            data = _loads(payload_json)
            svc = self._recording_service()
            svc.set_enabled(bool(data.get("enabled", False)))
            self._log(f"🎬 recording {'enabled' if svc.enabled() else 'disabled'}", "info")
            return {"ok": True, "enabled": svc.enabled()}
        return _reply(build)

    @Slot(result=str)
    def get_recording_settings(self) -> str:
        def build() -> dict:
            from app.services.recording import payloads
            return payloads.settings_payload(self._recording_service())
        return _reply(build)
