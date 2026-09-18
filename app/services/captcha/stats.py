"""Captcha statistics — local counters + provider balance.

Persisted atomically to `config/captcha_stats.json`; corrupt file → zeroed
store (RULE 13). The provider APIs expose no per-task history endpoint, so
task-level counters are local and the API contributes `getBalance`.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

_FILENAME = "captcha_stats.json"
_SITE_CAP = 50  # per-site map bounded; hosts beyond the cap fold into "*"

# event name → stored counter key (detected aggregates into a total)
_EVENT_KEYS = {
    "detected": "detected_total",
    "auto_solved": "auto_solved",
    "auto_failed": "auto_failed",
    "manual_solved": "manual_solved",
    "task_created": "tasks_created",
    "task_deleted": "tasks_deleted",
}
_COUNTER_KEYS = frozenset(_EVENT_KEYS.values())


class CaptchaStatsStore:
    """Counters for detection/solving + cached balance; one record() writer."""

    def __init__(self, config_dir: str | Path):
        self._path = Path(config_dir) / _FILENAME
        self._data: Dict[str, Any] = self._load()

    @staticmethod
    def _blank() -> Dict[str, Any]:
        return {
            "detected_total": 0,
            "auto_solved": 0,
            "auto_failed": 0,
            "manual_solved": 0,
            "tasks_created": 0,
            "tasks_deleted": 0,
            "last_error": "",
            "last_balance": None,
            "balance_at": "",
            "per_site": {},
        }

    @staticmethod
    def _valid_type(key: str, value: Any) -> bool:
        """Stored shape check — invalid values reset to the blank default."""
        if key == "per_site":
            return isinstance(value, dict)
        if key == "last_balance":
            return value is None or (isinstance(value, (int, float))
                                     and not isinstance(value, bool))
        if key in _COUNTER_KEYS:
            return isinstance(value, int) and not isinstance(value, bool)
        return isinstance(value, str)

    def _load(self) -> Dict[str, Any]:
        blank = self._blank()
        if not self._path.exists():
            return blank
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return blank
        if not isinstance(data, dict):
            return blank
        for k in blank:
            if not self._valid_type(k, data.get(k)):
                data[k] = blank[k]
        return data

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="_", suffix=".tmp", dir=str(self._path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            Path(tmp).replace(self._path)
        except Exception:
            pass  # stats are observability, never fatal to the job

    def _bump(self, key: str) -> int:
        self._data[key] = int(self._data.get(key, 0)) + 1
        return self._data[key]

    def record(self, event: str, site: str = "") -> None:
        """One counter event: detected|auto_solved|auto_failed|manual_solved
        |task_created|task_deleted. site = host, '' for global counters."""
        if event not in _EVENT_KEYS:
            return
        self._bump(_EVENT_KEYS[event])
        if site and event in ("detected", "auto_solved", "auto_failed", "manual_solved"):
            sites = self._data["per_site"]
            if site not in sites and len(sites) >= _SITE_CAP - 1:
                site = "*"  # cap the map; overflow folds into one entry
            per = sites.setdefault(site, {"detected": 0, "auto_solved": 0,
                                          "auto_failed": 0, "manual_solved": 0})
            per[event] = int(per.get(event, 0)) + 1
        self._save()

    def set_balance(self, balance: float) -> None:
        self._data["last_balance"] = round(float(balance), 4)
        self._data["balance_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._save()

    def set_last_error(self, error: str) -> None:
        self._data["last_error"] = str(error or "")[:120]
        self._save()

    @property
    def success_rate(self) -> float:
        """Auto-solve success: solved / (solved + failed); 0.0 when none."""
        solved = int(self._data.get("auto_solved", 0))
        failed = int(self._data.get("auto_failed", 0))
        denom = solved + failed
        return solved / denom if denom else 0.0

    @property
    def last_balance(self):
        return self._data.get("last_balance")

    @property
    def balance_at(self) -> str:
        return str(self._data.get("balance_at", ""))

    @property
    def last_error(self) -> str:
        return str(self._data.get("last_error", ""))

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self._data)
        d["auto_success_rate"] = round(self.success_rate, 4)
        return d
