"""Solver provider registry — 2Captcha + CapMonster Cloud (RULE 18 leaf).

Both providers speak the same anti-captcha-style JSON protocol (`createTask` /
`getTaskResult` / `getBalance`, `clientKey` in the POST body). A ProviderSpec
owns every per-provider difference as DATA (RULE 19: tables, not branches):
endpoint, task-type names, error classification, poll cadence, refund support.
Only the selected provider's official API host is ever contacted (RULE 20).

Sources: docs.capmonster.cloud (`docs/api/methods/get-task-result/`,
`docs/api/api-errors/`, `docs/captchas/recaptcha-v2-enterprise-task/`) and
2captcha.com/api-docs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

DEFAULT_PROVIDER = "2captcha"

# 2Captcha numeric errorIds → stable reason tokens (2captcha.com/api-docs).
_2CAPTCHA_ERRORS = {1: "unavailable", 2: "bad_key", 3: "no_credit", 16: "not_found"}

# CapMonster string errorCodes → the SAME stable tokens the solver already
# consumes (docs.capmonster.cloud/docs/api/api-errors/). Unmapped → task_error.
_CAPMONSTER_ERRORS = {
    "ERROR_KEY_DOES_NOT_EXIST": "bad_key",
    "ERROR_ZERO_BALANCE": "no_credit",
    "ERROR_NO_SUCH_CAPCHA_ID": "not_found",
    "WRONG_CAPTCHA_ID": "not_found",
    "ERROR_SERVICE_NOT_AVAILABLE": "unavailable",
    "ERROR_IP_NOT_ALLOWED": "unavailable",
    "ERROR_IP_BANNED": "unavailable",
    "ERROR_TOO_MUCH_REQUESTS": "unavailable",
}

# CapMonster reports "still solving" as an error code, not a status — the docs
# say to keep polling getTaskResult with >=2 s between calls.
_CAPMONSTER_PENDING = frozenset({"CAPTCHA_NOT_READY"})


def _reason_2captcha(error_id: Any, error_code: Any) -> str:
    """Map a 2Captcha numeric errorId to a stable reason token."""
    try:
        return _2CAPTCHA_ERRORS.get(int(error_id), "task_error")
    except (TypeError, ValueError):
        return "task_error"


def _reason_capmonster(error_id: Any, error_code: Any) -> str:
    """Map a CapMonster errorCode; CAPTCHA_NOT_READY means keep polling."""
    code = str(error_code or "")
    if code in _CAPMONSTER_PENDING:
        return "pending"
    return _CAPMONSTER_ERRORS.get(code, "task_error")


@dataclass(frozen=True)
class ProviderSpec:
    """One solver provider's wire facts; downstream code treats them uniformly.

    `task_type_for` falls back to the enterprise type for unknown kinds (the
    established default — the arena.ai dialog is enterprise). `enterprise_
    invisible`: only some providers document `isInvisible` for the ENTERPRISE
    task (2Captcha yes; CapMonster no) — the payload builder gates on it.
    """

    id: str
    title: str
    api_base: str
    poll_interval_sec: float
    task_types: Dict[str, str]
    can_delete: bool  # deleteTask (refund an abandoned task) support
    enterprise_invisible: bool
    error_reason: Callable[[Any, Any], str]

    def task_type_for(self, kind: str) -> str:
        return self.task_types.get(kind, self.task_types["recaptcha_enterprise"])


PROVIDERS: Dict[str, ProviderSpec] = {
    "2captcha": ProviderSpec(
        id="2captcha", title="2Captcha", api_base="https://api.2captcha.com",
        poll_interval_sec=5.0,  # docs-recommended getTaskResult cadence
        task_types={"recaptcha_enterprise": "RecaptchaV2EnterpriseTaskProxyless",
                    "recaptcha_v2": "RecaptchaV2TaskProxyless"},
        can_delete=True, enterprise_invisible=True, error_reason=_reason_2captcha),
    "capmonster": ProviderSpec(
        id="capmonster", title="CapMonster Cloud", api_base="https://api.capmonster.cloud",
        poll_interval_sec=3.0,  # docs floor is 2 s between polls, <=120 per task
        task_types={"recaptcha_enterprise": "RecaptchaV2EnterpriseTask",
                    "recaptcha_v2": "RecaptchaV2Task"},
        can_delete=False,  # no deleteTask; unsolved tasks are not charged
        enterprise_invisible=False,  # not a documented enterprise field there
        error_reason=_reason_capmonster),
}


def provider_for(pid: Any) -> ProviderSpec:
    """Spec for a provider id; unknown/missing falls back to the default."""
    if isinstance(pid, str) and pid in PROVIDERS:
        return PROVIDERS[pid]
    return PROVIDERS[DEFAULT_PROVIDER]
