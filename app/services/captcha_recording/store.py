"""Filesystem store for bounded, local captcha session artifacts.

The class keeps only the store operations the app calls; manifest shaping,
folder resolution and validation live in module functions so the class stays
inside the RULE 16 size budget.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .models import VALID_ACTOR_LABELS, VALID_RESULT_LABELS, new_session_id, utc_now
from .retention import prune_recordings
from .sanitize import safe_url

SCHEMA_VERSION = 2
_SUMMARY_KEYS = (
    "session_id", "eid", "tab", "source", "url", "kind", "started_at", "ended_at",
    "status", "outcome", "reason", "method", "acceptance", "verified", "job",
    "job_error", "actor_label", "result_label", "elapsed_ms", "event_count",
    "mutation_count", "network_count", "snapshot_count", "milestone_count", "truncated",
)


class RecordingStore:
    """Atomic manifests plus append-only events and compressed checkpoints."""

    def __init__(self, config_dir: str | Path):
        self.root = Path(config_dir) / "captcha_recordings"
        self.root.mkdir(parents=True, exist_ok=True)
        self.recover_interrupted()
        prune_recordings(self.root)

    def create(self, encounter: dict[str, Any]) -> dict[str, Any]:
        session_id = new_session_id()
        folder = self.root / session_id
        (folder / "snapshots").mkdir(parents=True, exist_ok=False)
        manifest = _new_manifest(session_id, encounter)
        _write_manifest(folder, manifest)
        return manifest

    def append_event(self, session_id: str, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with (_folder(self.root, session_id) / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()

    def write_snapshot(self, session_id: str, number: int, payload: dict[str, Any]) -> str:
        name = f"{number:06d}.json.gz"
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with gzip.open(_folder(self.root, session_id) / "snapshots" / name, "wb", compresslevel=6) as handle:
            handle.write(raw)
        return f"snapshots/{name}"

    def finish(self, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        folder = _folder(self.root, session_id)
        manifest = _read_manifest(folder)
        manifest.update(updates)
        manifest["ended_at"] = manifest.get("ended_at") or utc_now()
        _write_manifest(folder, manifest)
        prune_recordings(self.root)
        return manifest

    def apply_job(self, session_id: str, line: dict[str, Any]) -> dict[str, Any]:
        """Resolve the later image-job verdict onto a finalized session (RULE 4).

        `acceptance` keeps the observed solve-edge verdict; `verified` is the
        whole-job truth (`true` completed, `false` failed, `null` not joined yet).
        """
        folder = _folder(self.root, session_id)
        manifest = _read_manifest(folder)
        job = str(line.get("job", ""))[:20]
        manifest.update({"job": job, "job_error": str(line.get("error", ""))[:200],
                         "verified": True if job == "completed" else False if job == "failed" else None,
                         "job_corr": str(line.get("corr", ""))[:64], "job_at": utc_now()})
        event = {"seq": int(manifest.get("event_count") or 0), "at": manifest["job_at"],
                 "offset_ms": _since_ms(manifest.get("started_at", "")), "kind": "milestone",
                 "phase": "job_result",
                 "data": {"job": job, "error": manifest["job_error"],
                          "page_error": str(line.get("page_error", ""))[:200]}}
        self.append_event(session_id, event)
        manifest["event_count"] = event["seq"] + 1
        manifest["milestone_count"] = int(manifest.get("milestone_count") or 0) + 1
        _write_manifest(folder, manifest)
        return manifest

    def find_by_eid(self, eid: str) -> str:
        """Session id for an encounter id; '' when the session is gone (pruned)."""
        target = str(eid or "")
        if not target:
            return ""
        for folder in sorted(_session_folders(self.root), key=lambda path: path.name, reverse=True)[:200]:
            manifest = _read_manifest(folder, tolerate=True)
            if manifest.get("eid") == target:
                return str(manifest.get("session_id") or folder.name)
        return ""

    def list_sessions(self, limit: int | None = 200) -> list[dict[str, Any]]:
        rows = [row for row in (_summary(folder) for folder in _session_folders(self.root)) if row]
        rows.sort(key=lambda row: row.get("started_at", ""), reverse=True)
        if limit is None or int(limit) <= 0:
            return rows
        return rows[:min(int(limit), 1000)]

    def set_labels(self, session_id: str, actor: str, result: str | None) -> dict[str, Any]:
        if actor not in VALID_ACTOR_LABELS:
            raise ValueError("actor must be unknown, bot, manual, or mixed")
        if result is not None and result not in VALID_RESULT_LABELS:
            raise ValueError("result must be unknown, passed, or failed")
        folder = _folder(self.root, session_id)
        manifest = _read_manifest(folder)
        manifest["actor_label"] = actor
        if result is not None:
            manifest["result_label"] = result
        manifest["label_updated_at"] = utc_now()
        _write_manifest(folder, manifest)
        return _summary(folder)

    def recover_interrupted(self) -> None:
        """A writer that died mid-encounter must not look like a live session."""
        for folder in _session_folders(self.root):
            manifest = _read_manifest(folder, tolerate=True)
            if manifest and manifest.get("status") == "recording":
                manifest.update({"status": "interrupted", "outcome": "interrupted",
                                 "ended_at": utc_now()})
                _write_manifest(folder, manifest)


def _new_manifest(session_id: str, encounter: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "session_id": session_id,
        "eid": str(encounter.get("eid", "")), "tab": str(encounter.get("tab", "")),
        "source": str(encounter.get("source", "")),
        "url": safe_url(str(encounter.get("url", ""))),
        "kind": str(encounter.get("kind", "unknown")), "started_at": utc_now(),
        "ended_at": "", "status": "recording", "outcome": "", "reason": "", "method": "",
        "acceptance": "none", "verified": None, "job": "", "job_error": "",
        "actor_label": "unknown", "result_label": "unknown", "elapsed_ms": 0,
        "event_count": 0, "mutation_count": 0, "network_count": 0, "snapshot_count": 0,
        "milestone_count": 0, "truncated": [],
    }


def _summary(folder: Path) -> dict[str, Any]:
    manifest = _read_manifest(folder, tolerate=True)
    if not manifest:
        return {}
    summary = {key: manifest.get(key) for key in _SUMMARY_KEYS}
    summary["actor_label"] = summary.get("actor_label") or "unknown"
    summary["result_label"] = summary.get("result_label") or "unknown"
    return summary


def _session_folders(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return (path for path in root.iterdir() if path.is_dir())


def _folder(root: Path, session_id: str) -> Path:
    if not session_id or Path(session_id).name != session_id:
        raise ValueError("invalid session id")
    folder = root / session_id
    if not folder.is_dir():
        raise FileNotFoundError("recording not found")
    return folder


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


def _write_manifest(folder: Path, manifest: dict[str, Any]) -> None:
    """Atomically replace one session manifest."""
    target = folder / "manifest.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)


def _since_ms(started_at: str) -> int:
    """Milliseconds from a stored ISO start stamp to now (0 when unreadable)."""
    try:
        from datetime import datetime, timezone
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
    except Exception:
        return 0
