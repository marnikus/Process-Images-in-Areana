"""Auto-connect settings helpers — validation, storage keys, preset round-trip.

Plain functions (no Qt, no Bridge) so the storable shape of the feature is
testable on its own: what the Settings window sends in, what lands in
``config/session.json``, and what an arena preset carries.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from app.browser.autoconnect_config import (
    DEFAULT_INTERVAL_MS,
    MAX_INTERVAL_MS,
    MIN_INTERVAL_MS,
)
from app.browser.autoconnect_match import DEFAULT_PATTERN

MAX_PAGES_LIMIT = 100

# session.json key ↔ UI payload key ↔ default
FIELDS = {
    "enabled": ("autoconnect_enabled", True),
    "url_pattern": ("autoconnect_url_pattern", DEFAULT_PATTERN),
    "interval_ms": ("autoconnect_interval_ms", DEFAULT_INTERVAL_MS),
    "max_pages": ("autoconnect_max_pages", 0),
    "connect_primary": ("autoconnect_primary", True),
}


def clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _clean(data: Dict[str, Any], key: str, default: Any) -> Any:
    value = data.get(key, default)
    return default if value is None else value


def storable_from_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one Settings payload into ``session.json`` keyword arguments."""
    data = data if isinstance(data, dict) else {}
    pattern = str(_clean(data, "url_pattern", DEFAULT_PATTERN) or "").strip()
    return {
        "autoconnect_enabled": bool(_clean(data, "enabled", True)),
        "autoconnect_url_pattern": pattern,
        "autoconnect_interval_ms": clamp_int(_clean(data, "interval_ms", DEFAULT_INTERVAL_MS),
                                             DEFAULT_INTERVAL_MS, MIN_INTERVAL_MS, MAX_INTERVAL_MS),
        "autoconnect_max_pages": clamp_int(_clean(data, "max_pages", 0), 0, 0, MAX_PAGES_LIMIT),
        "autoconnect_primary": bool(_clean(data, "connect_primary", True)),
    }


def storable_from_preset(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Same validation for a preset document (older presets may miss keys)."""
    return storable_from_payload(doc if isinstance(doc, dict) else {})


def preset_doc(config) -> Dict[str, Any]:
    """The auto-connect part of an arena preset — every UI param storable."""
    return {
        "enabled": bool(config.enabled),
        "url_pattern": config.url_pattern,
        "interval_ms": int(config.interval_ms),
        "max_pages": int(config.max_pages),
        "connect_primary": bool(config.connect_primary),
    }


def describe(config) -> str:
    """One log line describing the stored auto-connect decision set."""
    limit = "" if config.max_pages <= 0 else f", max {config.max_pages} pages"
    state = "ON" if config.enabled else "OFF"
    return (
        f"💾 Auto-connect saved: {state} pattern “{config.url_pattern or DEFAULT_PATTERN}” "
        f"every {config.interval_ms // 1000}s on {config.endpoint}{limit}"
    )


def save_storable(set_state: Callable[..., Any], values: Dict[str, Any]) -> None:
    set_state(**values)
