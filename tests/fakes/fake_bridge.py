"""Fake Bridge — dict-based message bus, no QWebChannel (Phase 2).

RULE 18: file 150-300 LOC ideal, current ~120 LOC.
RULE 16: class LOC ≤150, methods ≤15.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List


class FakeBridge:
    """Fake bridge that records signals without Qt."""

    def __init__(self):
        self._logs: List[Dict] = []
        self._states: List[Dict] = []
        self._job_status: List[Dict] = []
        self._thumbnails: Dict[str, str] = {}
        self._handlers: Dict[str, List[Callable]] = {}

    def log(self, msg: str, level: str = "info"):
        self._logs.append({"msg": msg, "level": level})

    def emit_state(self, state: Dict):
        self._states.append(state)

    def emit_job_status(self, payload: Dict):
        self._job_status.append(payload)

    def emit_thumbnail(self, img_id: str, data_url: str):
        self._thumbnails[img_id] = data_url

    def get_logs(self) -> List[Dict]:
        return list(self._logs)

    def get_states(self) -> List[Dict]:
        return list(self._states)

    def get_job_status(self) -> List[Dict]:
        return list(self._job_status)

    def get_thumbnail(self, img_id: str) -> str:
        return self._thumbnails.get(img_id, "")

    def connect(self, signal: str, handler: Callable):
        self._handlers.setdefault(signal, []).append(handler)

    def emit(self, signal: str, *args: Any):
        for h in self._handlers.get(signal, []):
            try:
                h(*args)
            except Exception:
                pass


class FakeDialog:
    """Fake file dialog — returns tmp_path without Qt."""

    def __init__(self, return_path: str = ""):
        self._return_path = return_path

    def get_existing_directory(self, *a, **kw) -> str:
        return self._return_path
