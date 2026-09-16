"""CDP Protocol — pure logic extracted from cdp_client.py (Phase 2).

Goals:
- Separate transport (WebSocket, HTTP) from protocol (serialize/deserialize, tab parsing).
- Pure functions: no I/O, no socket, no urllib, <1ms per test, easy to unit test.
- RULE 18: file 150-300 LOC ideal, current ~120 LOC.
- RULE 16: function LOC ≤30, CC ≤10, nesting ≤4, params ≤4.

Extracted from app/browser/cdp_client.py:
- _is_devtools_url → is_devtools_url (pure)
- _normalize_ws_url → normalize_ws_url (pure)
- _parse_tabs → parse_tabs (pure)
- _filter_real_tabs → filter_real_tabs (pure)

Transport remains in cdp_client.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class TabInfo:
    """Pure tab info — same shape as cdp_client.TabInfo, but no Qt dependency."""
    id: str
    title: str
    url: str
    ws_url: str
    type: str = "page"


def is_devtools_url(url: str, title: str = "") -> bool:
    """Check if URL is devtools/chrome internal — pure string logic."""
    if not url:
        return True
    u = url.lower()
    t = (title or "").lower()
    prefixes = ("devtools://", "chrome://", "chrome-extension://", "about:", "edge://")
    if any(u.startswith(p) for p in prefixes):
        return True
    if "devtools/bundled" in u or "device_mode_emulation_frame" in u:
        return True
    return t.startswith("devtools")


def normalize_ws_url(ws_url: str, preferred_host: str, preferred_port: int) -> str:
    """Normalize ws_url host to preferred host/port — pure string."""
    if not ws_url:
        return ws_url
    try:
        m = re.match(r"^(ws://)([^:/]+)(?::(\d+))?(/.*)$", ws_url)
        if m:
            scheme, _host, _port, path = m.groups()
            return f"{scheme}{preferred_host}:{preferred_port}{path}"
        return ws_url
    except Exception:
        return ws_url


def _is_valid_tab_item(item: dict, include_devtools: bool) -> bool:
    if not isinstance(item, dict):
        return False
    t = item.get("type", "")
    if t and t != "page":
        return False
    url = item.get("url") or ""
    if not url:
        return False
    title = item.get("title") or ""
    if not include_devtools and is_devtools_url(url, title):
        return False
    return True


def _item_to_tab(item: dict, preferred_host: str, preferred_port: int) -> TabInfo:
    url = item.get("url") or ""
    ws_url = item.get("webSocketDebuggerUrl") or ""
    ws_norm = normalize_ws_url(ws_url, preferred_host, preferred_port) if ws_url else ws_url
    return TabInfo(
        id=item.get("id", ""),
        title=item.get("title", ""),
        url=url,
        ws_url=ws_norm,
        type=item.get("type", "page"),
    )


def parse_tabs(
    items: List[dict],
    preferred_host: str = "127.0.0.1",
    preferred_port: int = 9222,
    include_devtools: bool = True,
) -> List[TabInfo]:
    """Parse /json/list items into TabInfo — pure, no I/O."""
    tabs: List[TabInfo] = []
    for item in items or []:
        if not _is_valid_tab_item(item, include_devtools):
            continue
        tabs.append(_item_to_tab(item, preferred_host, preferred_port))
    return tabs


def filter_real_tabs(tabs: List[TabInfo]) -> List[TabInfo]:
    """Filter out devtools tabs — pure."""
    return [t for t in tabs if not is_devtools_url(t.url, t.title)]


def deduplicate_tabs_by_id(tabs: List[TabInfo], preferred_host: str = "127.0.0.1") -> List[TabInfo]:
    """Deduplicate tabs by id, preferring preferred_host — pure."""
    by_id: dict[str, TabInfo] = {}
    for t in tabs:
        key = t.id or t.ws_url
        if not key:
            continue
        if key not in by_id:
            by_id[key] = t
        else:
            existing = by_id[key]
            if not existing.ws_url and t.ws_url:
                by_id[key] = t
            elif preferred_host in t.ws_url and preferred_host not in existing.ws_url:
                by_id[key] = t
    return list(by_id.values())
