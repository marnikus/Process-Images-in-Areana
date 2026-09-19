"""Captcha signal/outcome types — pure data, no I/O (RULE 18 leaf module)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

SOLVABLE_KINDS = ("recaptcha_v2", "recaptcha_enterprise")


def _safe_count(res: Dict[str, Any]) -> int:
    try:
        return max(0, int(res.get("responseFields") or 0))
    except (TypeError, ValueError):
        return 0


def _evidence_kwargs(res: Dict[str, Any]) -> Dict[str, Any]:
    """Convert probe evidence keys without letting malformed data raise."""
    return {
        "integration": str(res.get("integration") or "unknown"),
        "anchor_present": bool(res.get("anchorPresent")), "anchor_visible": bool(res.get("anchorVisible")),
        "challenge_present": bool(res.get("challengePresent")),
        "challenge_visible": bool(res.get("challengeVisible")),
        "challenge_active": bool(res.get("challengeActive")),
        "challenge_title": str(res.get("challengeTitle") or "")[:120],
        "challenge_src": str(res.get("challengeSrc") or "")[:120],
        "challenge_identity": str(res.get("challengeIdentity") or "")[:120],
        "response_fields": _safe_count(res),
        "response_scope": str(res.get("responseScope") or "none"),
        "sitekey_source": str(res.get("sitekeySource") or "none"),
        "page_identity": str(res.get("pageIdentity") or "")[:120],
    }


@dataclass
class CaptchaSignal:
    """What the detect probe saw on one page."""

    visible: bool = False
    kind: str = "none"
    sitekey: str = ""
    page_url: str = ""
    is_invisible: bool = False
    dom: str = ""
    integration: str = "unknown"
    anchor_present: bool = False
    anchor_visible: bool = False
    challenge_present: bool = False
    challenge_visible: bool = False
    challenge_active: bool = False  # image-grid escalation visible (bframe)
    challenge_title: str = ""
    challenge_src: str = ""
    challenge_identity: str = ""
    response_fields: int = 0
    response_scope: str = "none"
    sitekey_source: str = "none"
    page_identity: str = ""
    @property
    def solvable(self) -> bool:
        """A 2Captcha task can be created for this signal."""
        return self.visible and self.kind in SOLVABLE_KINDS and bool(self.sitekey)

    @classmethod
    def from_result(cls, res: Optional[Any]) -> "CaptchaSignal":
        """Probe result to signal; malformed shape degrades to invisible."""
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except Exception:
                return cls()
        if not isinstance(res, dict):
            return cls()
        return cls(visible=bool(res.get("visible")),
                   kind=str(res.get("kind") or "none"),
                   sitekey=str(res.get("sitekey") or ""),
                   page_url=str(res.get("url") or ""),
                   is_invisible=bool(res.get("invisible")),
                   dom=str(res.get("dom") or ""),
                   **_evidence_kwargs(res))


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

    status: str = "none"
    reason: str = ""
    method: str = ""
    task_id: str = ""
    elapsed_sec: float = 0.0
    polls: int = 0
    attempts: int = 1  # paid 2Captcha tasks used (H1: bounded at 2)
    token_sec: float = 0.0
    token_fp: str = ""
    dialog_at_token: str = ""
    inject: str = ""
    page_error_at_s: float = 0.0
    page_error: str = ""
    # D2/F-B: bounded recording evidence (offsets in solve-relative seconds)
    task_created_sec: float = 0.0
    dialog_cleared_sec: float = 0.0
    page_identity: str = ""
    challenge_identity: str = ""
    continue_result: str = ""
