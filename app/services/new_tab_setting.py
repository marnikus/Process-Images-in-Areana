"""The Settings option behind I-79 — its keys, URL healing and the session save/load.

Split from the handover pipeline (`new_tab.py`, RULE 18: one responsibility per file): the UI
Settings save (`ui/panels/page_pool.py`) and the post-job reset (`cooldown_service`) need these
five names only, and must not import the CDP pipeline to reach them.

RULE 18: file ~50, func 4-20 LOC. Imports: stdlib only (a leaf module).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

SETTING_KEY = "new_chat_new_tab"
URL_KEY = "new_chat_new_tab_url"
# The other half of the guarded pair: `config_manager.DEFAULT_SESSION` seeds the
# same value for a fresh session. Neither side may import the other — this module
# is a stdlib-only leaf, and persistence must not reach up into services — so a
# test keeps them equal instead (audit #4 N3).
DEFAULT_URL = "https://arena.ai/image/direct?model_a=max"


def clean_url(raw: Any) -> str:
    """An http(s) URL with a host, else the default new-chat URL."""
    url = str(raw or "").strip()
    parts = urlparse(url)
    return url if parts.scheme in ("http", "https") and parts.netloc else DEFAULT_URL


def read_setting(get_state) -> dict:
    """`{"enabled", "url"}` from the session; unreadable values heal to the defaults."""
    try:
        return {"enabled": bool(get_state(SETTING_KEY, False)),
                "url": clean_url(get_state(URL_KEY, DEFAULT_URL))}
    except Exception:
        return {"enabled": False, "url": DEFAULT_URL}


def save_setting(config: Any, data: dict) -> dict:
    """Store `new_tab` / `new_tab_url` when the payload has them; returns the stored setting."""
    if "new_tab" not in data:
        return read_setting(config.get_state)
    stored = {"enabled": bool(data.get("new_tab", False)), "url": clean_url(data.get("new_tab_url"))}
    config.set_state(**{SETTING_KEY: stored["enabled"], URL_KEY: stored["url"]})
    return stored


def wanted_url(bridge: Any) -> str:
    """The new-chat URL when the option is on, '' when it is off."""
    config = getattr(bridge, "config", None)
    setting = read_setting(config.get_state) if config is not None else {"enabled": False}
    return setting["url"] if setting["enabled"] else ""
