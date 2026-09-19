"""Dedicated QWebChannel adapter for captcha recording summaries and labels."""

from __future__ import annotations

import json
from typing import Any

try:
    from PySide6.QtCore import QObject, QUrl, Slot
    from PySide6.QtGui import QDesktopServices
except ImportError:
    QDesktopServices = None
    QUrl = None
    class QObject:
        def __init__(self, *args, **kwargs):
            pass

    def Slot(*args, **kwargs):
        return lambda function: function


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
        try:
            rows = self.manager.list_sessions(limit)
            return json.dumps({"ok": True, "sessions": rows,
                               "total": self.manager.count_sessions()}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def recording_enabled(self) -> str:
        try:
            return json.dumps({"ok": True, "enabled": self.manager.is_enabled()},
                              ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(bool, result=str)
    def set_recording_enabled(self, enabled: bool) -> str:
        try:
            return json.dumps({"ok": True, "enabled": self.manager.set_enabled(enabled)},
                              ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def delete_session(self, session_id: str) -> str:
        try:
            row = self.manager.delete_session(session_id)
            return json.dumps({"ok": True, "session": row}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def set_label(self, session_id: str, label: str) -> str:
        try:
            row = self.manager.set_label(session_id, label)
            return json.dumps({"ok": True, "session": row}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def set_result_label(self, session_id: str, label: str) -> str:
        """D3: outcome label (unknown|passed|failed|mixed), independent of actor."""
        try:
            row = self.manager.set_result_label(session_id, label)
            return json.dumps({"ok": True, "session": row}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def cohort(self) -> str:
        try:
            from app.services.captcha_recording.cohort import cohort as build_cohort
            rows = self.manager.list_sessions(1000)
            return json.dumps({"ok": True, "cohort": build_cohort(rows)}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def get_session(self, session_id: str) -> str:
        try:
            details = self.manager.get_session(session_id)
            return json.dumps({"ok": True, "details": details}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def open_folder(self, session_id: str) -> str:
        try:
            path = self.manager.session_folder(session_id)
            if not self._opener(path):
                raise RuntimeError("operating system did not open the folder")
            return json.dumps({"ok": True, "path": path}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
