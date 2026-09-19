"""Bounded, schema-normalized read model for recording comparison."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from .retention import find_session_folder, is_valid_session_id


class EvidenceReader:
    """Read redacted artifacts and normalize schema-v1/v2 details."""

    def __init__(self, root: Path):
        self.root = root

    def details(self, session_id: str) -> dict[str, Any]:
        folder = self.folder(session_id)
        manifest = self._json(folder / "manifest.json")
        events = _events(folder / "events.jsonl")
        snapshots = _snapshots(folder / "snapshots")
        return {"manifest": manifest, "events": events, "snapshots": snapshots,
                "milestones": _milestones(folder / "events.jsonl"),
                "latest_snapshot": snapshots[-1] if snapshots else {},
                "evidence_complete": not bool(manifest.get("truncated"))}

    def folder(self, session_id: str) -> Path:
        if not is_valid_session_id(session_id):
            raise ValueError("invalid session id")
        folder = find_session_folder(self.root, session_id)
        if folder is None:
            raise FileNotFoundError("recording not found")
        return folder

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("recording document is not an object")
        return value


EVENT_WINDOW = 200


def _events(path: Path) -> list[dict[str, Any]]:
    """Last EVENT_WINDOW jsonl lines that parse as objects (bounded read model)."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-EVENT_WINDOW:]:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _snapshots(folder: Path) -> list[dict[str, Any]]:
    """Snapshot payloads available for the viewer — the latest one (bounded)."""
    latest = _snapshot(folder)
    return [latest] if latest else []


def _milestones(path: Path) -> list[dict[str, Any]]:
    """D2: every milestone event (full scan; the file is bounded by max_events)."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict) and value.get("kind") == "milestone":
            rows.append(value)
    return rows


def _snapshot(folder: Path) -> dict[str, Any]:
        files = sorted(folder.glob("*.json.gz")) if folder.is_dir() else []
        if not files:
            return {}
        with gzip.open(files[-1], "rt", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            return {}
        html = str(value.get("html", ""))
        return {"at": value.get("at", ""), "html": html[:20000],
                "truncated_for_view": len(html) > 20000}
