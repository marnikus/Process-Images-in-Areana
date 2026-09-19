"""CDP Client for Arena — compatibility facade (W2).

Implementation split into the app/browser/cdp/ package:
- cdp/endpoints.py — port probes + JSON fetches
- cdp/tabs.py      — /json/list tab fetch + diagnostics (TabInfo)
- cdp/connection.py— websocket connect lifecycle (candidates, lock, phases)
- cdp/transport.py — send + receive loop + disconnect
- cdp/dom.py       — evaluate/DOM queries/file input attach/highlight
- cdp/client.py    — CDPClient core (this class, unchanged surface)

This module re-exports the historical names so existing imports keep working.
"""
from __future__ import annotations

from .cdp import CDPClient, TabInfo, diagnose_sync, fetch_tabs_sync
from .cdp.connection import ws_candidates, ws_tab_id
from .cdp.dom import DEFAULT_FILE_INPUT_SELECTORS, highlight_js
from .cdp.endpoints import CANDIDATE_HOSTS, fetch_json_sync, hosts_to_try, is_port_open

__all__ = [
    "CDPClient",
    "TabInfo",
    "diagnose_sync",
    "fetch_tabs_sync",
    "CANDIDATE_HOSTS",
    "DEFAULT_FILE_INPUT_SELECTORS",
    "highlight_js",
    "hosts_to_try",
    "is_port_open",
    "fetch_json_sync",
    "ws_candidates",
    "ws_tab_id",
]
