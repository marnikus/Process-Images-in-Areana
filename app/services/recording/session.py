"""RecordingSession — header data for one captcha-encounter recording.

Pure data + validated (de)serialisation (RULE 13: never persist what we
cannot read back; a corrupt header is skipped with reason, never crashes).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

OUTCOMES = ("solved", "manual", "page_error", "token_stale",
            "auto_failed", "stopped", "none")
LABELS = ("", "bot_pass", "manual_pass")
HEADER_VERSION = 1


def _session_id(tab_id: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{str(tab_id or 'tab')[:6].upper()}"


@dataclass
class RecordingSession:
    """One captcha-encounter recording (header lives in session.json)."""

    id: str
    tab_id: str = ""
    url: str = ""
    trigger: str = ""
    kind: str = ""
    sitekey: str = ""
    started: str = ""
    stopped: str = ""
    status: str = "recording"  # recording | stopped
    outcome: str = "none"
    label: str = ""
    method: str = ""
    counters: Dict[str, int] = field(default_factory=lambda: {
        "events": 0, "snapshots": 0, "mutations": 0, "requests": 0})

    @classmethod
    def create(cls, tab_id: str, detect: Dict[str, str]) -> "RecordingSession":
        """detect = {url, trigger, kind, sitekey} gathered at captcha detect."""
        return cls(id=_session_id(tab_id), tab_id=str(tab_id or ""),
                   url=str(detect.get("url") or ""),
                   trigger=str(detect.get("trigger") or ""),
                   kind=str(detect.get("kind") or ""),
                   sitekey=str(detect.get("sitekey") or ""),
                   started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def bump(self, kind_key: str, n: int = 1) -> None:
        self.counters[kind_key] = int(self.counters.get(kind_key, 0)) + n

    def finalize(self, outcome: str, method: str = "") -> None:
        self.status = "stopped"
        self.outcome = outcome if outcome in OUTCOMES else "none"
        self.method = method
        self.stopped = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_header(self) -> Dict[str, Any]:
        return {"v": HEADER_VERSION, "id": self.id, "tab": self.tab_id,
                "url": self.url, "trigger": self.trigger, "kind": self.kind,
                "sitekey": self.sitekey, "started": self.started,
                "stopped": self.stopped, "status": self.status,
                "outcome": self.outcome, "label": self.label,
                "method": self.method, "counters": dict(self.counters)}

    @classmethod
    def from_header(cls, data: Any) -> Tuple["RecordingSession", str]:
        """(session, '') on success, (None, reason) when unreadable."""
        if not isinstance(data, dict):
            return None, "header not an object"
        if int(data.get("v", 0) or 0) != HEADER_VERSION:
            return None, f"unsupported header v={data.get('v')}"
        sid, err = _safe_session_id(data)
        if err:
            return None, err
        label = _str_field(data, "label")
        return cls(id=sid, tab_id=_str_field(data, "tab"), url=_str_field(data, "url"),
                   trigger=_str_field(data, "trigger"), kind=_str_field(data, "kind"),
                   sitekey=_str_field(data, "sitekey"), started=_str_field(data, "started"),
                   stopped=_str_field(data, "stopped"),
                   status=_str_field(data, "status") or "stopped",
                   outcome=_str_field(data, "outcome") or "none",
                   label=label if label in LABELS else "",
                   method=_str_field(data, "method"),
                   counters=_clean_counters(data.get("counters"))), ""


def _str_field(data: Dict[str, Any], key: str) -> str:
    return str(data.get(key) or "")


def _safe_session_id(data: Dict[str, Any]) -> Tuple[str, str]:
    sid = _str_field(data, "id")
    if not sid or "/" in sid or ".." in sid:
        return "", "missing or unsafe id"
    return sid, ""


def _clean_counters(raw: Any) -> Dict[str, int]:
    out = {"events": 0, "snapshots": 0, "mutations": 0, "requests": 0}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            pass  # RULE 13: keep what parses, skip junk counters
    return out
