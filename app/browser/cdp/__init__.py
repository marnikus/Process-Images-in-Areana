"""app.browser.cdp — Chrome DevTools Protocol package (W2 split of cdp_client)."""
from .client import CDPClient
from .tabs import TabInfo, diagnose_sync, fetch_tabs_sync

__all__ = ["CDPClient", "TabInfo", "diagnose_sync", "fetch_tabs_sync"]
