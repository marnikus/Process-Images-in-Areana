"""Dedicated QWebChannel adapter for captcha recording summaries and labels."""

from __future__ import annotations

import json
from typing import Any

try:
    from PySide6.QtCore import QObject, Slot
except ImportError:
    class QObject:
        def __init__(self, *args, **kwargs):
            pass

    def Slot(*args, **kwargs):
        return lambda function: function


class CaptchaRecordingsBridge(QObject):
    """Keep recording UI slots out of the already-large main Bridge."""

    def __init__(self, manager: Any, parent: Any = None):
        super().__init__(parent)
        self.manager = manager

    @Slot(int, result=str)
    def list_sessions(self, limit: int = 200) -> str:
        try:
            rows = self.manager.list_sessions(limit)
            return json.dumps({"ok": True, "sessions": rows}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def set_label(self, session_id: str, label: str) -> str:
        try:
            row = self.manager.set_label(session_id, label)
            return json.dumps({"ok": True, "session": row}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def get_session(self, session_id: str) -> str:
        try:
            details = self.manager.get_session(session_id)
            return json.dumps({"ok": True, "details": details}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
