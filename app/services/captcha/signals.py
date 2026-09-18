"""Captcha signal/outcome types — pure data, no I/O (RULE 18 leaf module)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

# kinds the solver can hand to 2Captcha
SOLVABLE_KINDS = ("recaptcha_v2", "recaptcha_enterprise")


@dataclass
class CaptchaSignal:
    """What the detect probe saw on one page."""

    visible: bool = False
    kind: str = "none"  # none | recaptcha_v2 | recaptcha_enterprise | image | probe_error
    sitekey: str = ""
    page_url: str = ""
    is_invisible: bool = False  # probe: iframe src size=invisible (no visible checkbox)
    dom: str = ""  # probe: semantic anchor (dialog|page : recaptcha-iframe|image|no-widget)

    @property
    def solvable(self) -> bool:
        """A 2Captcha task can be created for this signal."""
        return (
            self.visible
            and self.kind in SOLVABLE_KINDS
            and bool(self.sitekey)
        )

    @classmethod
    def from_result(cls, res: Optional[Any]) -> "CaptchaSignal":
        """Probe result to signal; CDP may yield a JSON string or a dict.
        Bad shape degrades to invisible (never raises)."""
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except Exception:
                return cls()
        if not isinstance(res, dict):
            return cls()
        return cls(
            visible=bool(res.get("visible")),
            kind=str(res.get("kind") or "none"),
            sitekey=str(res.get("sitekey") or ""),
            page_url=str(res.get("url") or ""),
            is_invisible=bool(res.get("invisible")),
            dom=str(res.get("dom") or ""),
        )


def host_of(url: str) -> str:
    """Hostname of a page URL (stats grouping key); '' when unparseable."""
    try:
        from urllib.parse import urlsplit
        return urlsplit(url or "").hostname or ""
    except Exception:
        return ""


@dataclass
class SolveOutcome:
    """Result of one handle_captcha flow (RULE 4: reason distinguishes broken)."""

    # none: no captcha | solved: auto-solved | auto_failed: attempt failed,
    # caller must fall back to the manual wait | manual: user cleared it |
    # stopped: stop requested mid-flow (RULE 7)
    status: str = "none"
    reason: str = ""
    method: str = ""  # auto | manual | ""
    task_id: str = ""
    elapsed_sec: float = 0.0
    polls: int = 0  # getTaskResult rounds (retry count)
    token_sec: float = 0.0  # solve start → token arrival
    token_fp: str = ""  # token fingerprint (shape only, RULE 20)
    dialog_at_token: str = ""  # visible | gone | "" (no token)
    inject: str = ""  # "scope=.. fields=.. cb=.." summary
    page_error_at_s: float = 0.0  # solve start → mid-solve page error
    page_error: str = ""
