"""One fetch for every browser, every cycle (2026-09-22).

Chrome on 9223 AND Firefox on 9224: each reconcile/scan/find cycle lists the
tabs of EVERY enabled browser at its own resolved endpoint — never just the
active one. `fetch_all_tabs` reads the live config, asks each endpoint in
its own protocol (`endpoints.enabled_targets`), and returns `TabInfo` rows
carrying `browser`/`protocol`, plus one error line per failed endpoint.

The handle helpers live here too: `tab_id_from_ws` reads the tab id out of
a CDP socket or an RDP `rdp://host:port#tab` handle, `browser_for_ws` names
the endpoint's browser from the live config, and `make_driver` builds the
matching tab driver. Browser imports stay lazy (panels never import browser
at top level); only the sibling `cdp_tools` is hoisted (no cycle).
"""

import asyncio
import re
from typing import Tuple
from urllib.parse import urlsplit

from .cdp_tools import browser_settings


def _host_base(config) -> Tuple[str, object]:
    """Shared debug host + base port from the live config."""
    host = config.get_state("cdp_host", "127.0.0.1") or "127.0.0.1"
    return host, config.get_state("cdp_port", 9222)


def fetch_all_tabs(config, timeout: float = 3.0):
    """(tabs, errors): every enabled browser's tabs + one line per failure."""
    from app.browser import endpoints
    from app.browser.cdp.tabs import TabInfo
    host, base = _host_base(config)
    refs, errors = endpoints.enabled_targets(browser_settings(config), host, base, timeout)
    tabs = [TabInfo(id=r.id, title=r.title, url=r.url, ws_url=r.ws_url,
                    browser=r.browser, protocol=r.protocol) for r in refs]
    return tabs, errors


async def fetch_all_tabs_async(config, timeout: float = 3.0):
    """The `fetch_tabs` callable the drivers delegate to (executor, non-blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fetch_all_tabs(config, timeout))


def endpoint_browsers(config) -> dict:
    """Resolved endpoint port → browser id, for every enabled browser."""
    from app.browser import browsers
    settings = browser_settings(config)
    _host, base = _host_base(config)
    out = {}
    for profile in browsers.PROFILES:
        entry = settings.get(profile.id) or {}
        if entry.get("enabled", True):
            out[browsers.resolve_port(base, profile, entry.get("port"))] = profile.id
    return out


def _ws_port(ws_url: str) -> int:
    """Endpoint port out of a CDP socket or RDP handle (0 when unparseable)."""
    try:
        return int(urlsplit(ws_url or "").netloc.rsplit(":", 1)[1])
    except Exception:
        return 0


def browser_for_ws(config, ws_url: str) -> str:
    """Browser id owning this tab handle ('' when no endpoint matches)."""
    return endpoint_browsers(config).get(_ws_port(ws_url), "")


def tab_id_from_ws(ws_url: str) -> str:
    """Tab id out of a handle: `/devtools/page/…` (CDP) or `#…` (RDP)."""
    found = re.search(r"/devtools/page/([^/#?]+)", ws_url or "")
    if found:
        return found.group(1)
    return urlsplit(ws_url or "").fragment or ""


def make_driver(host: str, port: int, ws_url: str):
    """The tab driver this handle speaks: CDP sockets → CDPClient, else RDP."""
    if (ws_url or "").strip().lower().startswith("rdp://"):
        from app.browser.rdp_driver import RdpDriver
        return RdpDriver(host=host, port=port)
    from app.browser.cdp_client import CDPClient
    return CDPClient(host=host, port=port)


def diagnose_endpoint(host: str, port: int, protocol: str, browser: str = "") -> dict:
    """One endpoint's diagnose dict in its own protocol (temp driver, sync)."""
    from app.browser import browsers
    if protocol == browsers.PROTOCOL_RDP:
        from app.browser.rdp_driver import RdpDriver
        return RdpDriver(host, port).diagnose_sync(host, port)
    from app.browser.cdp_client import CDPClient
    diag = CDPClient(host, port).diagnose_sync(host, port)
    diag["browser"] = browser
    for tab in diag.get("tabs", []):
        tab["browser"] = browser
    return diag


async def diagnose_active_async(config) -> dict:
    """Diagnose the ACTIVE browser's endpoint in its own protocol (executor)."""
    from app.browser import browsers
    from .cdp_tools import read_cdp_config, resolved_port
    loop = asyncio.get_event_loop()
    cfg = read_cdp_config(config)
    profile = browsers.profile_of(cfg["browser"]) or browsers.default_profile()
    port = resolved_port(cfg, profile.id)
    return await loop.run_in_executor(
        None, lambda: diagnose_endpoint(cfg["host"], port, profile.protocol, profile.id))
