# ideal-size: 60 lines reason=settings for new-tab handover, pure helpers that always change together
"""New-tab settings — URL cleaning, read/save, wanted URL."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

SETTING_KEY = "new_chat_new_tab"
URL_KEY = "new_chat_new_tab_url"
DEFAULT_URL = "https://arena.ai/image/direct?model_a=max"


def clean_url(raw: Any) -> str:
    """An http(s) URL with a host, else the default new-chat URL."""
    url = str(raw or "").strip()
    parts = urlparse(url)
    return url if parts.scheme in ("http", "https") and parts.netloc else DEFAULT_URL


def read_setting(get_state) -> dict:
    """`{"enabled", "url"}` from the session; unreadable values heal to defaults."""
    try:
        return {"enabled": bool(get_state(SETTING_KEY, False)),
                "url": clean_url(get_state(URL_KEY, DEFAULT_URL))}
    except Exception:
        return {"enabled": False, "url": DEFAULT_URL}


def save_setting(config: Any, data: dict) -> dict:
    """Store `new_tab` / `new_tab_url` when payload has them; returns stored setting."""
    if "new_tab" not in data:
        return read_setting(config.get_state)
    stored = {"enabled": bool(data.get("new_tab", False)),
              "url": clean_url(data.get("new_tab_url"))}
    config.set_state(**{SETTING_KEY: stored["enabled"], URL_KEY: stored["url"]})
    return stored


def wanted_url(bridge: Any) -> str:
    """The new-chat URL when option is on, '' when off."""
    config = getattr(bridge, "config", None)
    setting = read_setting(config.get_state) if config is not None else {"enabled": False}
    return setting["url"] if setting["enabled"] else ""
