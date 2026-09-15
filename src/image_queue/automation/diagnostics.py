"""Consent-only diagnostics; never serialize arbitrary page data, URLs, selectors or errors."""

from typing import Any

from image_queue.workspace.execution import TRANSITIONS


def diagnostic_summary(consent: bool, event: dict[str, Any]) -> dict[str, Any]:
    if consent is not True:
        return {}
    status = event.get("phase")
    return {
        "phase": status if isinstance(status, str) and status in TRANSITIONS else "unknown",
        "live_adapter_enabled": False,
    }
