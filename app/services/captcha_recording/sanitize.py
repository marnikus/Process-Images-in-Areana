"""Pure redaction helpers for local captcha recordings."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_SECRET_KEY = re.compile(r"(authorization|cookie|token|secret|password|response)", re.I)
_LONG_TOKEN = re.compile(r"(?<![\w-])[A-Za-z0-9_-]{80,}(?![\w-])")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
MAX_TEXT = 65_536


def safe_url(url: str) -> str:
    """Retain route identity while dropping query credentials and fragments."""
    try:
        parts = urlsplit(str(url or ""))
        host = parts.hostname or ""
        host = f"[{host}]" if ":" in host else host
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, host + port, parts.path, "", ""))
    except Exception:
        return ""


def redact_text(value: Any, limit: int = MAX_TEXT) -> str:
    """Bound text and replace common bearer/opaque token shapes."""
    text = str(value or "")[:max(0, int(limit))]
    text = _BEARER.sub("[REDACTED_BEARER]", text)
    return _LONG_TOKEN.sub("[REDACTED_TOKEN]", text)


def clean_mapping(data: Any) -> Any:
    """Recursively redact secret-named fields in a JSON-compatible value."""
    if isinstance(data, dict):
        return {str(key): _clean_item(str(key), value) for key, value in data.items()}
    if isinstance(data, list):
        return [clean_mapping(value) for value in data]
    if isinstance(data, str):
        return redact_text(data, 4096)
    return data


def _clean_item(key: str, value: Any) -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    return clean_mapping(value)


def textual_mime(mime: str) -> bool:
    value = str(mime or "").lower()
    return value.startswith("text/") or any(part in value for part in ("json", "xml", "javascript"))
