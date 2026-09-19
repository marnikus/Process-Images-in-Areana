"""Watcher config and state — C9 split from watcher.py for RULE18 file 150-300.

Config and state are pure dataclasses, no Qt, no side effects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class WatcherConfig:
    enabled: bool = False
    check_interval_ms: int = 2000
    captcha_timeout_sec: int = 300
    generation_timeout_sec: int = 600
    auto_pause_jobs: bool = True


@dataclass
class WatcherState:
    status: str = "idle"
    last_check: float = 0
    last_generation_details: Dict[str, Any] = field(default_factory=dict)
    last_captcha_detected: bool = False
    waiting_since: Optional[float] = None
    waiting_kind: Optional[str] = None
    checks_count: int = 0
    generation_waits: int = 0
    captcha_waits: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "last_check": self.last_check,
            "last_check_human": time.strftime("%H:%M:%S", time.localtime(self.last_check)) if self.last_check else "never",
            "checks_count": self.checks_count,
            "generation_waits": self.generation_waits,
            "captcha_waits": self.captcha_waits,
            "waiting_since": self.waiting_since,
            "waiting_kind": self.waiting_kind,
            "waiting_duration": int(time.time() - self.waiting_since) if self.waiting_since else 0,
            "last_generation_details": self.last_generation_details,
            "last_captcha_detected": self.last_captcha_detected,
        }
