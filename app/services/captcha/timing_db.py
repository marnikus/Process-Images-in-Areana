"""Per-site CAPTCHA solve timing intelligence.

Records solve durations per host and classifies sites as
impossible / marginal / fast / unknown so the solver can skip
auto-solve on sites where tokens arrive after page patience.

Persisted atomically to `config/captcha_timing.json`; corrupt →
blank (RULE 13). No tokens, keys, or credentials stored (RULE 20).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

_FILENAME = "captcha_timing.json"
_MAX_HOSTS = 50
_MIN_ATTEMPTS_FOR_VERDICT = 3
_PATIENCE_FALLBACK_SEC = 60

# verdict thresholds (fraction of page patience)
_IMPOSSIBLE_THRESHOLD = 1.0   # p95 > patience
_MARGINAL_THRESHOLD = 0.7     # avg > patience * 0.7
_FAST_THRESHOLD = 0.5          # avg < patience * 0.5
_SUCCESS_RATE_FLOOR = 0.10     # <10% success → impossible


@dataclass(frozen=True)
class TimingSample:
    """One observed solve attempt (RULE 16 params gate; RULE 19 parameter object)."""

    solve_sec: float
    token_sec: float = 0.0
    success: bool = False
    kind: str = ""
    page_patience_sec: Optional[float] = None  # None = keep the stored patience


def _blank_entry(host: str) -> Dict[str, Any]:
    return {
        "host": host,
        "attempts": 0,
        "successes": 0,
        "failures": 0,
        "avg_solve_sec": 0.0,
        "avg_token_sec": 0.0,
        "p95_solve_sec": 0.0,
        "page_patience_sec": _PATIENCE_FALLBACK_SEC,
        "kind": "unknown",
        "verdict": "unknown",
        "last_updated": "",
    }


class TimingDatabase:
    """Per-site timing records for adaptive solve decisions."""

    def __init__(self, config_dir: str | Path):
        self._path = Path(config_dir) / _FILENAME
        self._data: Dict[str, Dict[str, Any]] = self._load()

    def record_attempt(self, host: str, sample: TimingSample) -> None:
        """Record one solve attempt's timing data."""
        if not host:
            return
        entry = self._data.get(host) or _blank_entry(host)
        n = entry["attempts"]
        entry["attempts"] = n + 1
        entry["avg_solve_sec"] = _rolling(entry["avg_solve_sec"], sample.solve_sec, n)
        entry["avg_token_sec"] = _rolling(entry["avg_token_sec"], sample.token_sec, n)
        entry["p95_solve_sec"] = _update_p95(entry["p95_solve_sec"], sample.solve_sec, n)
        if sample.success:
            entry["successes"] += 1
        else:
            entry["failures"] += 1
        if sample.kind:
            entry["kind"] = sample.kind
        if sample.page_patience_sec and sample.page_patience_sec > 0:
            entry["page_patience_sec"] = float(sample.page_patience_sec)
        entry["verdict"] = classify_verdict(entry)
        entry["last_updated"] = _utc_now()
        self._data[host] = entry
        self._cap_hosts()
        self._save()

    def get_verdict(self, host: str) -> str:
        """Return verdict for a host: impossible|marginal|fast|unknown."""
        entry = self._data.get(host)
        if entry is None:
            return "unknown"
        return str(entry.get("verdict", "unknown"))

    def get_effective_timeout(self, host: str, user_timeout: float) -> float:
        """Adaptive timeout: min(user, patience * 0.8) when data exists."""
        entry = self._data.get(host)
        if entry is None or entry["attempts"] < _MIN_ATTEMPTS_FOR_VERDICT:
            return user_timeout
        patience = float(entry.get("page_patience_sec", _PATIENCE_FALLBACK_SEC))
        adaptive = patience * 0.8
        return min(user_timeout, adaptive) if adaptive > 0 else user_timeout

    def get_entry(self, host: str) -> Dict[str, Any]:
        """Read-only copy of one host's timing data."""
        entry = self._data.get(host)
        return dict(entry) if entry else {}

    def to_dict(self) -> Dict[str, Dict[str, Any]]:
        """Full snapshot for status/display."""
        return {k: dict(v) for k, v in self._data.items()}

    def _cap_hosts(self) -> None:
        if len(self._data) <= _MAX_HOSTS:
            return
        by_time = sorted(self._data.items(),
                         key=lambda kv: kv[1].get("last_updated", ""))
        for key, _ in by_time[:len(self._data) - _MAX_HOSTS]:
            del self._data[key]

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save(self) -> None:
        try:
            import tempfile
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="_", suffix=".tmp",
                                       dir=str(self._path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            Path(tmp).replace(self._path)
        except Exception:
            pass  # timing is observability, never fatal to the job


def classify_verdict(entry: Dict[str, Any]) -> str:
    """Classify a host's solve viability from its timing data."""
    attempts = int(entry.get("attempts", 0))
    if attempts < _MIN_ATTEMPTS_FOR_VERDICT:
        return "unknown"
    patience = float(entry.get("page_patience_sec", _PATIENCE_FALLBACK_SEC))
    p95 = float(entry.get("p95_solve_sec", 0))
    avg = float(entry.get("avg_solve_sec", 0))
    successes = int(entry.get("successes", 0))
    success_rate = successes / attempts if attempts > 0 else 0.0
    if p95 > patience or success_rate < _SUCCESS_RATE_FLOOR:
        return "impossible"
    if avg > patience * _MARGINAL_THRESHOLD:
        return "marginal"
    if avg < patience * _FAST_THRESHOLD:
        return "fast"
    return "marginal"


def _rolling(current: float, new_value: float, n: int) -> float:
    """Exponential moving average with alpha=0.3."""
    if n == 0:
        return new_value
    alpha = 0.3
    return current * (1 - alpha) + new_value * alpha


def _update_p95(current_p95: float, new_value: float, n: int) -> float:
    """Approximate p95 using exponential smoothing biased high."""
    if n == 0:
        return new_value
    alpha = 0.2
    return current_p95 * (1 - alpha) + new_value * alpha


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")