"""Dedicated QWebChannel adapter for captcha recording summaries and labels.

Every slot answers with one JSON envelope: `_reply` turns the payload builder's
dict into `{"ok": true, ...}` or `{"ok": false, "error": ...}`, so a raising
manager can never take the panel down (RULE 13).
"""

from __future__ import annotations

import json
from typing import Any, Callable

try:
    from PySide6.QtCore import QObject, QUrl, Slot
    from PySide6.QtGui import QDesktopServices
except ImportError:
    QDesktopServices = None
    QUrl = None

    class QObject:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

    def Slot(*args, **kwargs):
        _ = (args, kwargs)
        return lambda function: function


def _reply(build: Callable[[], dict]) -> str:
    """Run one payload builder, returning its JSON or an error envelope."""
    try:
        return json.dumps(build(), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def _open_local_folder(path: str) -> bool:
    if QDesktopServices is None or QUrl is None:
        raise RuntimeError("desktop folder opening is unavailable")
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))


class CaptchaRecordingsBridge(QObject):
    """Keep recording UI slots out of the already-large main Bridge."""

    def __init__(self, manager: Any, parent: Any = None, opener: Any = None):
        super().__init__(parent)
        self.manager = manager
        self._opener = opener or _open_local_folder

    @Slot(int, result=str)
    def list_sessions(self, limit: int = 1000) -> str:
        return _reply(lambda: {"ok": True, "sessions": self.manager.list_sessions(limit),
                               "total": self.manager.count_sessions()})

    @Slot(result=str)
    def recording_enabled(self) -> str:
        return _reply(lambda: {"ok": True, "enabled": self.manager.is_enabled()})

    @Slot(bool, result=str)
    def set_recording_enabled(self, enabled: bool) -> str:
        return _reply(lambda: {"ok": True, "enabled": self.manager.set_enabled(enabled)})

    @Slot(str, result=str)
    def delete_session(self, session_id: str) -> str:
        return _reply(lambda: {"ok": True, "session": self.manager.delete_session(session_id)})

    @Slot(str, str, str, result=str)
    def set_labels(self, session_id: str, actor: str, result: str) -> str:
        return _reply(lambda: {"ok": True, "session": self.manager.set_labels(session_id, actor,
                                                                              result)})

    @Slot(str, result=str)
    def get_session(self, session_id: str) -> str:
        return _reply(lambda: {"ok": True, "details": self.manager.get_session(session_id)})

    @Slot(result=str)
    def cohort(self) -> str:
        """D3: actor x result matrix over every retained session (summaries only)."""
        def build() -> dict:
            from app.services.captcha_recording.cohort import cohort as build_cohort
            rows = self.manager.list_sessions(1000)
            return {"ok": True, "cohort": build_cohort(rows)}
        return _reply(build)

    @Slot(str, str, result=str)
    def compare_sessions(self, left_id: str, right_id: str) -> str:
        return _reply(lambda: {"ok": True,
                               "comparison": self.manager.compare_sessions(left_id, right_id)})

    @Slot(str, result=str)
    def open_folder(self, session_id: str) -> str:
        def build() -> dict:
            path = self.manager.session_folder(session_id)
            if not self._opener(path):
                raise RuntimeError("operating system did not open the folder")
            return {"ok": True, "path": path}
        return _reply(build)
