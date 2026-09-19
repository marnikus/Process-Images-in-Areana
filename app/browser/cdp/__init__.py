"""CDP package facade (C2) — re-exports for backward compat."""
from .client import CDPClient
from .tabs import TabInfo, fetch_tabs_sync, CANDIDATE_HOSTS
from .probe import diagnose_sync

__all__ = ["CDPClient", "TabInfo", "fetch_tabs_sync", "diagnose_sync", "CANDIDATE_HOSTS"]
