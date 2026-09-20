"""Captcha watcher signal / result / status types — pure data, no I/O.

Leaf module (RULE 18): nothing here imports Qt, CDP or the SDK.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

# Only kinds the SDK solver knows how to submit (recaptcha family).
SOLVABLE_KINDS = ("recaptcha_v2", "recaptcha_enterprise")


@dataclass
class CaptchaSignal:
    """What the detect probe saw on one page (contract of captcha_js/detect.js)."""

    visible: bool = False
    kind: str = ""          # recaptcha_v2 | recaptcha_enterprise | hcaptcha | ... | probe_error
    sitekey: str = ""
    invisible: bool = False
    page_url: str = ""

    @property
    def solvable(self) -> bool:
        """Visible recaptcha challenge with a sitekey → the SDK can take it."""
        return self.visible and self.kind in SOLVABLE_KINDS and bool(self.sitekey)

    @classmethod
    def from_result(cls, res: Any, page_url: str = "") -> "CaptchaSignal":
        """Parse the probe payload; anything malformed → not visible (fail open)."""
        if not isinstance(res, dict):
            return cls(page_url=page_url)
        return cls(
            visible=bool(res.get("visible")),
            kind=str(res.get("kind") or ""),
            sitekey=str(res.get("sitekey") or "").strip(),
            invisible=bool(res.get("invisible")),
            page_url=str(res.get("url") or page_url or ""),
        )


@dataclass
class SolveResult:
    """Outcome of one SDK solve; `token` never leaves the process (RULE 20)."""

    ok: bool = False
    token: str = ""
    task_id: str = ""
    error: str = ""
    elapsed_s: float = 0.0

    def masked(self) -> Dict[str, Any]:
        """Log-safe view: token length only, never the token."""
        return {"ok": self.ok, "task_id": self.task_id, "error": self.error,
                "elapsed_s": round(self.elapsed_s, 1), "token_len": len(self.token)}


@dataclass
class WatcherStatus:
    """Live counters for the Watcher window (UI-safe, no secrets)."""

    running: bool = False
    has_key: bool = False
    sdk_available: bool = True
    provider: str = "2captcha"          # active solving provider id (B10)
    provider_label: str = "2Captcha"
    tabs_seen: int = 0
    ticks: int = 0
    solved_total: int = 0
    failed_total: int = 0
    solving_tab: str = ""
    last_error: str = ""
    last_tick_at: float = 0.0
    last_solved_at: float = 0.0
    balance: Optional[float] = None

    def touch(self) -> None:
        self.last_tick_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
