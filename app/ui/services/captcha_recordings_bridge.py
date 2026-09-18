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
    """Keep recording UI slots out of the already-large main Bridge.

    Talks to the recording *catalog* (list/label/compare/remove), never to the
    lifecycle manager, so a UI call can never touch a live recorder.
    """

    def __init__(self, catalog: Any, parent: Any = None, opener: Any = None):
        super().__init__(parent)
        self.catalog = catalog
        self._opener = opener or _open_local_folder

    @Slot(int, result=str)
    def list_sessions(self, limit: int = 200) -> str:
        try:
            rows = self.catalog.list_sessions(limit)
            return json.dumps({"ok": True, "sessions": rows}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def list_all_sessions(self) -> str:
        try:
            rows = self.catalog.list_sessions(None)
            return json.dumps({"ok": True, "sessions": rows}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def delete_session(self, session_id: str) -> str:
        try:
            deleted = self.catalog.delete_session(session_id)
            return json.dumps({"ok": True, "deleted": deleted}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def delete_all_sessions(self) -> str:
        try:
            result = self.catalog.delete_all_sessions()
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def undo_delete(self) -> str:
        try:
            restored = self.catalog.undo_delete()
            return json.dumps({"ok": True, "restored": restored}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def set_label(self, session_id: str, label: str) -> str:
        try:
            row = self.catalog.set_label(session_id, label)
            return json.dumps({"ok": True, "session": row}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, str, result=str)
    def set_labels(self, session_id: str, actor: str, result: str) -> str:
        try:
            row = self.catalog.set_labels(session_id, actor, result)
            return json.dumps({"ok": True, "session": row}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def get_session(self, session_id: str) -> str:
        try:
            details = self.catalog.get_session(session_id)
            return json.dumps({"ok": True, "details": details}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def compare_sessions(self, left_id: str, right_id: str) -> str:
        try:
            report = self.catalog.compare_sessions(left_id, right_id)
            return json.dumps({"ok": True, "comparison": report}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def open_folder(self, session_id: str) -> str:
        try:
            path = self.catalog.session_folder(session_id)
            if not self._opener(path):
                raise RuntimeError("operating system did not open the folder")
            return json.dumps({"ok": True, "path": path}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
