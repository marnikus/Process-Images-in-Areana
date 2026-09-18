"""Filesystem store for bounded, local captcha session artifacts."""

from __future__ import annotations

import gzip
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .models import VALID_LABELS, day_folder_for, new_session_id, utc_now
from .retention import drop_empty_day, find_session_folder, prune_recordings, session_folders
from .sanitize import safe_url

SCHEMA_VERSION = 1
SETTINGS_NAME = "settings.json"


def recording_enabled(root: Path) -> bool:
    """Records-window toggle; missing/corrupt settings default to on."""
    try:
        data = json.loads((root / SETTINGS_NAME).read_text(encoding="utf-8"))
        return bool(data.get("recording_enabled", True))
    except Exception:
        return True


def save_recording_enabled(root: Path, enabled: bool) -> None:
    (root / SETTINGS_NAME).write_text(
        json.dumps({"recording_enabled": bool(enabled)}), encoding="utf-8")


class RecordingStore:
    """Atomic manifests plus append-only events and compressed checkpoints."""

    def __init__(self, config_dir: str | Path):
        self.root = Path(config_dir) / "captcha_recordings"
        self.root.mkdir(parents=True, exist_ok=True)
        self.recover_interrupted()
        prune_recordings(self.root)

    def create(self, encounter: dict[str, Any]) -> dict[str, Any]:
        session_id = new_session_id()
        folder = self.root / day_folder_for(session_id) / session_id
        (folder / "snapshots").mkdir(parents=True, exist_ok=False)
        manifest = self._new_manifest(session_id, encounter)
        self._write_manifest(folder, manifest)
        return manifest

    def session_folder(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("invalid session id")
        folder = find_session_folder(self.root, session_id)
        if folder is None:
            raise FileNotFoundError("recording not found")
        return folder

    def append_event(self, session_id: str, event: dict[str, Any]) -> None:
        folder = self.session_folder(session_id)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()

    def write_snapshot(self, session_id: str, number: int, payload: dict[str, Any]) -> str:
        folder = self.session_folder(session_id) / "snapshots"
        name = f"{number:06d}.json.gz"
        target = folder / name
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with gzip.open(target, "wb", compresslevel=6) as handle:
            handle.write(raw)
        return f"snapshots/{name}"

    def finish(self, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        folder = self.session_folder(session_id)
        manifest = self._read_manifest(folder)
        manifest.update(updates)
        manifest["ended_at"] = manifest.get("ended_at") or utc_now()
        self._write_manifest(folder, manifest)
        prune_recordings(self.root)
        return manifest

    def list_sessions(self, limit: int = 1000) -> list[dict[str, Any]]:
        rows = [self._summary(folder) for folder in session_folders(self.root)]
        clean = [row for row in rows if row]
        clean.sort(key=lambda row: row.get("started_at") or "", reverse=True)
        return clean[:max(1, min(int(limit), 1000))]

    def count_sessions(self) -> int:
        return len(session_folders(self.root))

    def delete_session(self, session_id: str) -> dict[str, Any]:
        folder = self.session_folder(session_id)
        shutil.rmtree(folder, ignore_errors=True)
        drop_empty_day(self.root, folder.parent)
        return {"session_id": session_id, "deleted": True}

    def set_label(self, session_id: str, label: str) -> dict[str, Any]:
        if label not in VALID_LABELS:
            raise ValueError("label must be unknown, bot, or manual")
        folder = self.session_folder(session_id)
        manifest = self._read_manifest(folder)
        manifest["actor_label"] = label
        manifest["label_updated_at"] = utc_now()
        self._write_manifest(folder, manifest)
        return self._summary(folder)

    def recover_interrupted(self) -> None:
        for folder in session_folders(self.root):
            manifest = self._read_manifest(folder, tolerate=True)
            if manifest and manifest.get("status") == "recording":
                manifest.update({"status": "interrupted", "outcome": "interrupted", "ended_at": utc_now()})
                self._write_manifest(folder, manifest)

    def _new_manifest(self, session_id: str, encounter: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "eid": str(encounter.get("eid", "")),
            "tab": str(encounter.get("tab", "")),
            "source": str(encounter.get("source", "")),
            "url": safe_url(str(encounter.get("url", ""))),
            "kind": str(encounter.get("kind", "unknown")),
            "started_at": utc_now(),
            "ended_at": "",
            "status": "recording",
            "outcome": "",
            "reason": "",
            "method": "",
            "actor_label": "unknown",
            "elapsed_ms": 0,
            "event_count": 0,
            "mutation_count": 0,
            "network_count": 0,
            "snapshot_count": 0,
            "truncated": [],
        }

    def _summary(self, folder: Path) -> dict[str, Any]:
        manifest = self._read_manifest(folder, tolerate=True)
        if not manifest:
            return {}
        keys = (
            "session_id", "eid", "tab", "source", "url", "kind", "started_at",
            "ended_at", "status", "outcome", "reason", "method", "actor_label",
            "elapsed_ms", "event_count", "mutation_count", "network_count",
            "snapshot_count", "truncated",
        )
        return {key: manifest.get(key) for key in keys}

    @staticmethod
    def _read_manifest(folder: Path, tolerate: bool = False) -> dict[str, Any]:
        try:
            data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("manifest is not an object")
            return data
        except Exception:
            if tolerate:
                return {}
            raise

    @staticmethod
    def _write_manifest(folder: Path, manifest: dict[str, Any]) -> None:
        target = folder / "manifest.json"
        temp = target.with_suffix(".json.tmp")
        text = json.dumps(manifest, ensure_ascii=False, indent=2)
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, target)
