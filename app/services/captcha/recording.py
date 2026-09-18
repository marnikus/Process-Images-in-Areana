"""Redacted CAPTCHA session recordings and manual review labels.

This module is storage/policy only. It never stores tokens, cookies, credentials,
private prompt/image content, or raw network bodies (RULE 20).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

SCHEMA = 1
LABELS = ("unknown", "manual_pass", "bot_pass", "manual_fail", "bot_fail")
MAX_EVENTS = 5000
MAX_SNAPSHOT = 512 * 1024
MAX_TEXT = 500
_SECRET = re.compile(r"(?i)(token|cookie|authorization|clientkey|password|secret|g-recaptcha-response)")


def _clip(value: Any, limit: int = MAX_TEXT) -> Any:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        return [_clip(x, limit) for x in value[:100]]
    if isinstance(value, dict):
        return {str(k): _clip(v, limit) for k, v in value.items()
                if not _SECRET.search(str(k))}
    return value


def _atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_clip(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class RecordingSession:
    """One bounded recording; event writes are atomic and best effort."""

    store: "RecordingStore"
    rid: str
    eid: str
    corr: str
    started: float
    active: bool = True
    seq: int = 0

    def event(self, kind: str, data: Optional[Dict[str, Any]] = None) -> None:
        if not self.active or self.seq >= MAX_EVENTS:
            return
        row = {"v": SCHEMA, "rid": self.rid, "eid": self.eid, "corr": self.corr,
               "seq": self.seq, "at_s": round(time.monotonic() - self.started, 3),
               "kind": kind, **(data or {})}
        self.seq += 1
        with self.store.events(self.rid).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_clip(row), ensure_ascii=False) + "\n")

    def snapshot(self, data: Dict[str, Any]) -> None:
        if not self.active:
            return
        payload = {"v": SCHEMA, "rid": self.rid, "seq": self.seq,
                   "at_s": round(time.monotonic() - self.started, 3), **data}
        raw = json.dumps(_clip(payload), ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_SNAPSHOT:
            payload["dom"] = {"truncated": True}
        _atomic(self.store.root / self.rid / "snapshots" / f"{self.seq:06d}.json", payload)
        self.event("snapshot", {"snapshot": self.seq})

    def stop(self, reason: str, outcome: str = "") -> None:
        if not self.active:
            return
        self.event("recording_stopped", {"reason": reason, "outcome": outcome})
        self.active = False
        manifest = self.store.load(self.rid) or {}
        manifest.update({"ended_at": time.time(), "duration_s": round(time.monotonic() - self.started, 3),
                         "terminal_reason": reason, "terminal_outcome": outcome,
                         "event_count": self.seq})
        self.store.save_manifest(self.rid, manifest)
        self.store.refresh_index()


class RecordingStore:
    """Atomic disk store for redacted recordings and review labels."""

    def __init__(self, config_dir: str):
        self.root = Path(config_dir) / "captcha_sessions"
        self.index = self.root / "index.json"

    def events(self, rid: str) -> Path:
        return self.root / rid / "events.jsonl"

    def save_manifest(self, rid: str, manifest: Dict[str, Any]) -> None:
        _atomic(self.root / rid / "manifest.json", manifest)

    def load(self, rid: str) -> Optional[Dict[str, Any]]:
        path = self.root / rid / "manifest.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def start(self, eid: str, corr: str, tab: str, signal: Dict[str, Any]) -> RecordingSession:
        rid = uuid.uuid4().hex[:10]
        now = time.time()
        manifest = {"v": SCHEMA, "rid": rid, "eid": eid, "corr": corr, "tab": tab,
                    "started_at": now, "label": "unknown", "label_note": "",
                    "signal": _clip(signal), "event_count": 0}
        self.save_manifest(rid, manifest)
        session = RecordingSession(self, rid, eid, corr, time.monotonic())
        session.event("recording_started", {"tab": tab})
        self.refresh_index()
        return session

    def refresh_index(self) -> None:
        rows = []
        for path in sorted(self.root.glob("*/manifest.json"), reverse=True):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        _atomic(self.index, rows[:500])

    def list(self) -> Iterable[Dict[str, Any]]:
        try:
            value = json.loads(self.index.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError):
            self.refresh_index()
            return self.list()

    def label(self, rid: str, label: str, note: str = "") -> bool:
        if label not in LABELS:
            return False
        manifest = self.load(rid)
        if manifest is None:
            return False
        manifest["label"] = label
        manifest["label_note"] = str(note or "")[:MAX_TEXT]
        _atomic(self.root / rid / "manifest.json", manifest)
        with self.events(rid).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"v": SCHEMA, "rid": rid, "kind": "label_changed",
                                 "label": label, "note": manifest["label_note"],
                                 "at": time.time()}, ensure_ascii=False) + "\n")
        self.refresh_index()
        return True

    def load_events(self, rid: str) -> list:
        try:
            return [json.loads(line) for line in self.events(rid).read_text(encoding="utf-8").splitlines() if line]
        except (OSError, ValueError):
            return []

    def delete(self, rid: str) -> bool:
        path = self.root / rid
        if not path.exists():
            return False
        import shutil
        shutil.rmtree(path)
        self.refresh_index()
        return True
