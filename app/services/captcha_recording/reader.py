"""Bounded, schema-normalized read model for recording comparison."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

_EVENT_KEYS = frozenset({"seq", "at", "offset_ms", "at_ms", "kind", "payload"})
VIEW_HTML_LIMIT = 20_000


class EvidenceReader:
    """Read redacted artifacts and normalize schema-v1/v2 details."""

    def __init__(self, root: Path):
        self.root = root

    def details(self, session_id: str) -> dict[str, Any]:
        folder = self.folder(session_id)
        manifest = self._json(folder / "manifest.json")
        manifest.setdefault("result_label", "unknown")
        events = _events(folder / "events.jsonl")
        snapshots = _snapshots(folder / "snapshots")
        return {"manifest": manifest, "events": events, "snapshots": snapshots,
                "latest_snapshot": snapshots[-1] if snapshots else {},
                "evidence_complete": not bool(manifest.get("truncated"))}

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


def _events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-500:]:
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(_event(value))
        except (json.JSONDecodeError, TypeError):
            continue
    return rows


def _event(value: dict[str, Any]) -> dict[str, Any]:
    payload = value.get("payload")
    if not isinstance(payload, dict):
        payload = {key: item for key, item in value.items() if key not in _EVENT_KEYS}
    return {"seq": value.get("seq", 0), "at": value.get("at", ""),
            "offset_ms": value.get("offset_ms", value.get("at_ms", 0)),
            "kind": value.get("kind", "unknown"), "payload": payload}


def _snapshots(folder: Path) -> list[dict[str, Any]]:
    files = sorted(folder.glob("*.json.gz")) if folder.is_dir() else []
    rows = []
    for path in files[-25:]:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                value = json.load(handle)
            if isinstance(value, dict):
                rows.append(_snapshot(path.name, value))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return rows


def _snapshot(name: str, value: dict[str, Any]) -> dict[str, Any]:
    html = str(value.get("html", ""))
    return {"name": name, "at": value.get("at", ""),
            "offset_ms": value.get("offset_ms", value.get("at_ms", 0)),
            "reason": value.get("reason", ""), "sha256": value.get("sha256", ""),
            "html": html[:VIEW_HTML_LIMIT], "truncated_for_view": len(html) > VIEW_HTML_LIMIT}
