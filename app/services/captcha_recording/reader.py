"""Bounded, schema-normalized read model for recording comparison.

Legacy schema-v1 events stay readable (`at_ms`/flattened payloads are normalized
to `offset_ms`/`payload`), but every session is presented as the same model: a
milestone timeline, an acceptance/verification verdict, a bounded checkpoint
index, a per-class network summary and explicit completeness warnings.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

_EVENT_KEYS = frozenset({"seq", "at", "offset_ms", "at_ms", "kind", "payload"})
#: Schema-v1 sessions only had coarse `state` rows; map them to named edges.
LEGACY_STATE_PHASES = {"detected": "detected",
                       "auto_attempt_finished": "auto_attempt_finished",
                       "recording_finished": "session_end"}
VIEW_HTML_LIMIT = 20_000
MAX_EVENTS = 500
MAX_SNAPSHOTS = 25
MAX_MILESTONES = 80
MAX_NETWORK_CLASSES = 12


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
        milestones = _milestones(events)
        return {"manifest": manifest, "events": events, "snapshots": snapshots,
                "latest_snapshot": snapshots[-1] if snapshots else {},
                "milestones": milestones,
                "acceptance": manifest.get("acceptance", "none"),
                "verified": manifest.get("verified"),
                "job": manifest.get("job", ""),
                "network_summary": _network_summary(events),
                "warnings": _warnings(manifest, snapshots, milestones),
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
    for line in path.read_text(encoding="utf-8").splitlines()[-MAX_EVENTS:]:
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


def _milestones(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Named edges, newest schema first; legacy `state` rows are mapped for old sessions."""
    rows = []
    for event in events:
        payload = event.get("payload") or {}
        if event.get("kind") == "milestone":
            phase = str(payload.get("phase", ""))
            data = payload.get("data")
        elif event.get("kind") == "state":
            phase = LEGACY_STATE_PHASES.get(str(payload.get("state", "")), "")
            data = {"legacy": True, "outcome": payload.get("outcome", "")}
        else:
            continue
        if phase:
            rows.append({"phase": phase, "offset_ms": int(event.get("offset_ms") or 0),
                         "data": data if isinstance(data, dict) else {}})
    return rows[-MAX_MILESTONES:]


def _snapshots(folder: Path) -> list[dict[str, Any]]:
    files = sorted(folder.glob("*.json.gz")) if folder.is_dir() else []
    rows = []
    for path in files[-MAX_SNAPSHOTS:]:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append(_snapshot(path.name, value))
    return rows


def _snapshot(name: str, value: dict[str, Any]) -> dict[str, Any]:
    html = str(value.get("html", ""))
    return {"name": name, "at": value.get("at", ""),
            "offset_ms": value.get("offset_ms", value.get("at_ms", 0)),
            "reason": value.get("reason", ""), "sha256": value.get("sha256", ""),
            "html": html[:VIEW_HTML_LIMIT], "truncated_for_view": len(html) > VIEW_HTML_LIMIT}


def _network_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordered endpoint classes with counts — the bounded network diff input."""
    counter: Counter = Counter()
    for event in events:
        if not str(event.get("kind", "")).startswith("network_"):
            continue
        payload = event.get("payload") or {}
        label = f"{event.get('kind')}|{payload.get('category', '')}|{payload.get('method', '')}"
        if payload.get("status") is not None:
            label += f"|{payload.get('status')}"
        if payload.get("error"):
            label += "|error"
        counter[label] += 1
    return [{"class": label, "count": count}
            for label, count in counter.most_common(MAX_NETWORK_CLASSES)]


def _warnings(manifest: dict[str, Any], snapshots: list[dict[str, Any]],
              milestones: list[dict[str, Any]]) -> list[str]:
    """RULE 4: say what is missing or unproven instead of implying a clean pass."""
    warnings: list[str] = []
    truncated = manifest.get("truncated") or []
    if truncated:
        warnings.append(f"evidence truncated: {', '.join(str(item) for item in truncated)}")
    if not _starts_with_detected(milestones):
        warnings.append("missing initial (detected) edge")
    if not any(row.get("reason") == "resolved" for row in snapshots):
        warnings.append("missing resolved DOM checkpoint")
    warnings.extend(_proof_warnings(manifest))
    return warnings


def _starts_with_detected(milestones: list[dict[str, Any]]) -> bool:
    return bool(milestones) and milestones[0].get("phase") == "detected"


def _proof_warnings(manifest: dict[str, Any]) -> list[str]:
    """Acceptance is only a candidate until the image job joins its verdict."""
    warnings: list[str] = []
    if manifest.get("acceptance") == "accepted_candidate" and manifest.get("verified") is None:
        warnings.append("acceptance candidate — image job has not confirmed it yet")
    if manifest.get("verified") is False:
        warnings.append("job failed after the captcha edge (candidate refuted)")
    probe_errors = int(manifest.get("probe_errors") or 0)
    if probe_errors:
        warnings.append(f"{probe_errors} page-probe errors during capture")
    return warnings
