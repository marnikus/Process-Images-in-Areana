"""Bounded read model for the local recording comparison UI."""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import Any

_ENVELOPE_KEYS = frozenset({"seq", "at", "offset_ms", "kind"})


class EvidenceReader:
    """Read already-redacted evidence without returning unbounded artifacts."""

    def __init__(self, root: Path):
        self.root = root

    def details(self, session_id: str) -> dict[str, Any]:
        folder = self.folder(session_id)
        manifest = self._json(folder / "manifest.json")
        return {
            "manifest": manifest,
            "events": self._events(folder / "events.jsonl"),
            "latest_snapshot": self._snapshot(folder / "snapshots"),
        }

    def folder(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("invalid session id")
        folder = self.root / session_id
        if not folder.is_dir():
            raise FileNotFoundError("recording not found")
        return folder

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("recording document is not an object")
        return value

    @staticmethod
    def _events(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-200:]
        rows = []
        for line in lines:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(_adapt_event(value))
            except (json.JSONDecodeError, TypeError):
                continue
        return rows

    @staticmethod
    def _snapshot(folder: Path) -> dict[str, Any]:
        files = sorted(folder.glob("*.json.gz")) if folder.is_dir() else []
        if not files:
            return {}
        with gzip.open(files[-1], "rt", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            return {}
        html = str(value.get("html", ""))
        at_ms = _parse_at_ms(value.get("at"))
        return {"at_ms": at_ms, "html": html[:20000],
                "truncated_for_view": len(html) > 20000}


def _adapt_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Reshape a recorder event for the comparison UI.

    Recorder writes flat keys: {seq, at, offset_ms, kind, ...extra}.
    The comparison JS expects: {at_ms, kind, payload}.
    """
    adapted: dict[str, Any] = {
        "at_ms": raw.get("offset_ms", 0),
        "kind": raw.get("kind", "?"),
    }
    payload = {k: v for k, v in raw.items() if k not in _ENVELOPE_KEYS}
    if payload:
        adapted["payload"] = payload
    return adapted


def _parse_at_ms(value: Any) -> int:
    """Best-effort: turn an ISO UTC string into epoch-ms, or return 0."""
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return 0
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, OSError):
        return 0