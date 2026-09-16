"""Auto-connect configuration — one control per decision (RULE 10), all storable.

Stored in ``config/session.json`` (and in arena preset JSON) as:

``autoconnect_enabled``        scan + connect matching pages without a manual Add
``autoconnect_url_pattern``    URL string filter, e.g. ``arena.ai`` (comma list ok)
``autoconnect_interval_ms``    re-scan period; also the connection watchdog
``autoconnect_max_pages``      0 = connect every matching page
``autoconnect_primary``        also point the primary CDP client at the first page
``cdp_host`` / ``cdp_port``    the only host:port that is scanned (e.g. 9223)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from .autoconnect_match import DEFAULT_PATTERN, compile_patterns

MIN_INTERVAL_MS = 1000
MAX_INTERVAL_MS = 600_000
DEFAULT_INTERVAL_MS = 5000


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


@dataclass
class AutoConnectConfig:
    """Plain values — the service never reaches into the config store itself."""

    enabled: bool = True
    url_pattern: str = DEFAULT_PATTERN
    interval_ms: int = DEFAULT_INTERVAL_MS
    max_pages: int = 0
    connect_primary: bool = True
    host: str = "127.0.0.1"
    port: int = 9222
    patterns: list = None  # type: ignore[assignment]

    def __post_init__(self):
        self.url_pattern = str(self.url_pattern or "")
        self.interval_ms = _clamp(_as_int(self.interval_ms, DEFAULT_INTERVAL_MS), MIN_INTERVAL_MS, MAX_INTERVAL_MS)
        self.max_pages = max(0, _as_int(self.max_pages, 0))
        self.host = str(self.host or "127.0.0.1").strip() or "127.0.0.1"
        self.port = _clamp(_as_int(self.port, 9222), 1, 65535)
        self.patterns = compile_patterns(self.url_pattern)

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "url_pattern": self.url_pattern,
            "patterns": list(self.patterns),
            "interval_ms": self.interval_ms,
            "max_pages": self.max_pages,
            "connect_primary": bool(self.connect_primary),
            "host": self.host,
            "port": self.port,
            "endpoint": self.endpoint,
        }


def config_from_getter(get: Callable[[str, Any], Any]) -> AutoConnectConfig:
    """Build the config from a ``ConfigManager.get_state``-like callable."""
    return AutoConnectConfig(
        enabled=bool(get("autoconnect_enabled", True)),
        url_pattern=str(get("autoconnect_url_pattern", DEFAULT_PATTERN) or ""),
        interval_ms=_as_int(get("autoconnect_interval_ms", DEFAULT_INTERVAL_MS), DEFAULT_INTERVAL_MS),
        max_pages=_as_int(get("autoconnect_max_pages", 0), 0),
        connect_primary=bool(get("autoconnect_primary", True)),
        host=str(get("cdp_host", "127.0.0.1") or "127.0.0.1"),
        port=_as_int(get("cdp_port", 9222), 9222),
    )
