"""Shim for backward compat — new implementation lives in app.browser.cdp (C2)."""
from .cdp.client import CDPClient
from .cdp.tabs import TabInfo, fetch_tabs_sync, CANDIDATE_HOSTS, _is_port_open, _fetch_json_sync
from .cdp.probe import diagnose_sync

__all__ = ["CDPClient", "TabInfo", "fetch_tabs_sync", "diagnose_sync", "CANDIDATE_HOSTS"]
