"""Auto-connect glue — Chrome/page-pool adapters used by the Bridge (spec 01-04).

``PageConnector`` is the only place that knows how the Bridge talks to Chrome and
to the page pool, so the detection/linking logic stays free of Qt and of Bridge
internals. A scan therefore runs exactly the same in tests and in production.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.browser.autoconnect_config import AutoConnectConfig
from app.browser.autoconnect_match import page_id_from_ws


async def fetch_pool_tabs(cdp: Any, cfg: AutoConnectConfig) -> list:
    """Read the page list from the configured CDP host:port only (spec 02).

    An empty answer is not believed on its own: :func:`confirm_empty` reads the
    endpoint once more so an unreachable port surfaces as broken (RULE 4) instead
    of "no tabs open", which would reap pages that are still linked.
    """
    if cdp is not None:
        tabs = await cdp.fetch_tabs(host=cfg.host, port=cfg.port, strict_host=True)
        if tabs:
            return tabs
    return await confirm_empty(cfg)


async def confirm_empty(cfg: AutoConnectConfig) -> list:
    """Second read of the same endpoint, for the empty/broken verdict.

    Chrome with zero open pages answers ``[]`` and no error (empty); a refused or
    closed port answers with an error (broken), which is raised so the pass keeps
    the pages it already linked and simply retries on the next one.
    """
    from app.browser.cdp_client import fetch_tabs_sync

    tabs, err, tried = await asyncio.to_thread(fetch_tabs_sync, cfg.host, cfg.port, 3.0, True)
    if err and not tabs:
        raise ConnectionError(f"{err} (tried {', '.join(tried)})")
    return tabs


def pool_has_page(pool: Any, tab_id: str) -> bool:
    try:
        return bool(pool and pool.get_page(tab_id))
    except Exception:
        return False


def primary_is_linked(cdp: Any) -> bool:
    """True when the primary CDP session already owns a tab (never steal it)."""
    try:
        return bool(cdp and cdp.is_connected and getattr(cdp, "_current_tab_id", ""))
    except Exception:
        return False


class PageConnector:
    """Fetch / link / unlink adapters bound to one Bridge instance."""

    def __init__(self, bridge, config_getter):
        self._bridge = bridge
        self._config_getter = config_getter

    @property
    def config(self) -> AutoConnectConfig:
        return self._config_getter()

    async def fetch(self) -> list:
        return await fetch_pool_tabs(self._bridge.cdp, self.config)

    async def link(self, page: dict) -> bool:
        """Link one matched page: into the pool always, primary session if free."""
        ws_url = page.get("ws_url") or ""
        if not ws_url:
            return False
        bridge = self._bridge
        tab_id = page.get("page_id") or page_id_from_ws(ws_url)
        if self.config.connect_primary and not primary_is_linked(bridge.cdp):
            await self._link_primary(ws_url, tab_id)
        await bridge._do_connect_page_pool(ws_url)
        linked = pool_has_page(bridge._page_pool, tab_id)
        if linked:
            self._restore_cooldown(tab_id)
        return linked

    def _restore_cooldown(self, tab_id: str) -> None:
        """Re-apply a persisted wall-clock pause so auto-linking never frees a cooling tab."""
        restore = getattr(self._bridge, "_restore_cooldown", None)
        if not callable(restore):
            return
        try:
            restore(tab_id)
        except Exception as e:
            self._bridge._log(f"Cooldown restore skipped for {tab_id[:12]}: {e}", "warn")

    async def _link_primary(self, ws_url: str, tab_id: str) -> None:
        try:
            await self._bridge._do_connect_tab(ws_url)
        except Exception as e:
            self._bridge._log(f"Auto-connect primary failed for {tab_id[:12]}: {e}", "warn")

    def unlink(self, tab_id: str) -> bool:
        """Drop a page that closed or stopped matching — sync, called mid-scan."""
        pool = self._bridge._page_pool
        if not pool:
            return False
        removed = pool.remove_page(tab_id)
        self._bridge._emit_pool_status()
        return removed
