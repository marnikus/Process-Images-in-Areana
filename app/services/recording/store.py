"""RecordingStore — session folders on disk (git-ignored logs/recordings/).

Layout per session: session.json (header) + events.jsonl (append-only) +
NNNN.html snapshots. Atomic writes, validated reads; a corrupt session is
skipped with reason, never crashes the list (RULE 4/13). The output is not
the queue (RULE 14): deleting a queue entry never touches recordings — only
explicit user delete here does.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sanitizer import MAX_HTML_LINE, bound_str, redact_dom_html
from .session import LABELS, RecordingSession

_SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{6,40}$")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class RecordingStore:
    """Filesystem persistence for captcha session recordings."""

    def __init__(self, root: str):
        self.root = Path(root)

    def _dir(self, session_id: str) -> Optional[Path]:
        if not _SAFE_ID.match(session_id or ""):
            return None
        return self.root / session_id

    def create(self, session: RecordingSession, first_html: str = "") -> bool:
        d = self._dir(session.id)
        if d is None or d.exists():
            return False
        try:
            d.mkdir(parents=True, exist_ok=False)
            _atomic_write(d / "session.json",
                          json.dumps(session.to_header(), ensure_ascii=False, indent=1))
            if first_html:
                self.add_snapshot(session, first_html)
            return True
        except Exception:
            return False

    def append_event(self, session: RecordingSession, kind: str,
                     data: Dict[str, Any]) -> None:
        d = self._dir(session.id)
        if d is None:
            return
        line = {"ts": data.pop("ts", None) or _now(), "seq": session.counters.get("events", 0),
                "kind": bound_str(kind, 20)}
        reserved = ("ts", "seq", "kind")
        line.update({k: v for k, v in data.items() if k not in reserved})
        try:
            with open(d / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False)[:4000] + "\n")
            session.bump("events")
        except Exception:
            pass

    def add_snapshot(self, session: RecordingSession, html: str) -> str:
        d = self._dir(session.id)
        if d is None or not html:
            return ""
        idx = session.counters.get("snapshots", 0)
        name = f"{idx:04d}.html"
        try:
            lines = [ln[:MAX_HTML_LINE] for ln in redact_dom_html(html).splitlines()]
            _atomic_write(d / name, "\n".join(lines))
            session.bump("snapshots")
            self.append_event(session, "snapshot", {"file": name})
            return name
        except Exception:
            return ""

    def finalize(self, session: RecordingSession) -> None:
        d = self._dir(session.id)
        if d is None:
            return
        try:
            _atomic_write(d / "session.json",
                          json.dumps(session.to_header(), ensure_ascii=False, indent=1))
        except Exception:
            pass

    def list_sessions(self) -> Tuple[List[Dict[str, Any]], List[str]]:
        """(valid headers newest-first, skip reasons)."""
        out, skipped = [], []
        if not self.root.is_dir():
            return out, skipped
        for d in sorted(self.root.iterdir(), reverse=True):
            if not d.is_dir() or not _SAFE_ID.match(d.name):
                continue
            header, err = self._read_header(d)
            if header is None:
                skipped.append(f"{d.name}: {err}")
                continue
            out.append(header)
        return out, skipped

    def _read_header(self, d: Path) -> Tuple[Optional[Dict[str, Any]], str]:
        try:
            data = json.loads((d / "session.json").read_text(encoding="utf-8"))
        except Exception:
            return None, "unreadable header"
        session, err = RecordingSession.from_header(data)
        if session is None:
            return None, err
        header = session.to_header()
        header["snapshot_names"] = self._snapshot_names(d)
        return header, ""

    def _snapshot_names(self, d: Path) -> List[str]:
        try:
            return sorted(p.name for p in d.glob("*.html"))
        except Exception:
            return []

    def set_label(self, session_id: str, label: str) -> Tuple[bool, str]:
        if label not in LABELS:
            return False, f"invalid label {label!r}"
        d = self._dir(session_id)
        if d is None:
            return False, "unknown session"
        session, err = RecordingSession.from_header(self._raw_header(d))
        if session is None:
            return False, err
        session.label = label
        self.finalize(session)
        return True, label

    def _raw_header(self, d: Path) -> Any:
        try:
            return json.loads((d / "session.json").read_text(encoding="utf-8"))
        except Exception:
            return None

    def load_events(self, session_id: str, limit: int = 400) -> List[Dict[str, Any]]:
        d = self._dir(session_id)
        return _read_events(d, limit) if d is not None else []

    def load_snapshot(self, session_id: str, name: str) -> str:
        d = self._dir(session_id)
        return _read_snapshot(d, name) if d is not None else ""

    def delete(self, session_id: str) -> bool:
        d = self._dir(session_id)
        if d is None or not d.is_dir():
            return False
        try:
            for f in d.iterdir():
                if f.is_file():
                    f.unlink()
            d.rmdir()
            return True
        except Exception:
            return False


def _read_events(d: Path, limit: int) -> List[Dict[str, Any]]:
    if not (d / "events.jsonl").exists():
        return []
    out = []
    try:
        for line in (d / "events.jsonl").read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return out


def _read_snapshot(d: Path, name: str) -> str:
    if not re.match(r"^\d{4}\.html$", name or ""):
        return ""
    try:
        return (d / name).read_text(encoding="utf-8")
    except Exception:
        return ""


def _now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
