"""CDP tab listing + diagnostics over HTTP /json endpoints (W2 split).

Wraps the pure protocol from cdp_protocol.py and merges results across
candidate hosts (deduplicated by tab id).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .endpoints import fetch_json_sync, hosts_to_try, is_port_open
from ..cdp_protocol import (
    TabInfo as PureTabInfo,
    parse_tabs as pure_parse_tabs,
)

log = __import__("logging").getLogger("arena")


@dataclass
class TabInfo:
    """One Chrome tab as exposed by /json/list."""
    id: str = ""
    title: str = ""
    url: str = ""
    ws_url: str = ""
    type: str = "page"


def _parse_tabs(items: List[dict], preferred_host: str = "127.0.0.1",
                preferred_port: int = 9222, include_devtools: bool = True) -> List[TabInfo]:
    """Parse raw /json/list items into TabInfo rows."""
    pure_tabs = pure_parse_tabs(items, preferred_host, preferred_port, include_devtools)
    return [TabInfo(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url, type=t.type) for t in pure_tabs]


def _tab_key(tab: TabInfo) -> str:
    """Dedup key: tab id, falling back to ws_url (same page via both hosts)."""
    return tab.id or tab.ws_url


def _prefer_tab(existing: TabInfo, candidate: TabInfo, preferred_host: str) -> bool:
    """True when candidate should replace existing in the merged map."""
    if not existing.ws_url and candidate.ws_url:
        return True
    return preferred_host in candidate.ws_url and preferred_host not in existing.ws_url


def _merge_tabs(merged: dict, tabs: List[TabInfo], preferred_host: str,
                first_wins: bool = False) -> None:
    """Merge one host's tabs into the id-keyed map (first wins, preferred host upgrades)."""
    for t in tabs:
        key = _tab_key(t)
        if not key:
            continue
        if key not in merged or (not first_wins and _prefer_tab(merged[key], t, preferred_host)):
            merged[key] = t


def _tabs_from_host(host: str, port: int, timeout: float):
    """(tabs, error) from one host's /json/list (empty tabs on failure)."""
    url = f"http://{host}:{port}/json/list"
    if not is_port_open(host, port, timeout=1.0):
        return [], f"Port {port} not open on {host} (connection refused) — is Chrome running with --remote-debugging-port={port}?"
    data, err = fetch_json_sync(url, timeout=timeout)
    if err:
        return [], err
    return _parse_tabs(data, preferred_host=host, preferred_port=port), ""


def fetch_tabs_sync(host: str = "127.0.0.1", port: int = 9222,
                    timeout: float = 3.0) -> Tuple[List[TabInfo], str, List[str]]:
    """Try to fetch tabs synchronously, trying candidate hosts and merging results.
    Returns (tabs, error, tried_urls) — deduplicated by id.
    """
    tried: List[str] = []
    merged: dict = {}
    last_err = ""
    for h in hosts_to_try(host):
        tried.append(f"http://{h}:{port}/json/list")
        tabs, err = _tabs_from_host(h, port, timeout)
        if err:
            last_err = err
            continue
        _merge_tabs(merged, tabs, preferred_host=host)
    if merged:
        return list(merged.values()), "", tried
    return [], last_err or "No Chrome tabs found — Chrome not responding on any host", tried


def _diagnose_host(host: str, port: int, preferred_host: str) -> tuple:
    """One host's diagnostic check: port probe, /json/version, /json/list.
    Returns (check dict, parsed TabInfo list)."""
    check = {"host": host, "port_open": False, "version": None, "version_error": "",
             "list_count": 0, "list_error": "", "tabs": []}
    check["port_open"] = is_port_open(host, port, timeout=1.0)
    v_data, v_err = fetch_json_sync(f"http://{host}:{port}/json/version", timeout=2.0)
    check["version"], check["version_error"] = (None, v_err) if v_err else (v_data, "")
    tabs = _diagnose_list(check, host, port, preferred_host)
    return check, tabs


def _diagnose_list(check: dict, host: str, port: int, preferred_host: str) -> List[TabInfo]:
    """Fill /json/list fields of a diagnostic check; returns parsed tabs."""
    l_data, l_err = fetch_json_sync(f"http://{host}:{port}/json/list", timeout=3.0)
    if l_err:
        check["list_error"] = l_err
        return []
    tabs = _parse_tabs(l_data, preferred_host=preferred_host, preferred_port=port)
    check["list_count"] = len(tabs)
    check["tabs"] = [{"title": t.title[:80], "url": t.url, "id": t.id} for t in tabs[:10]]
    return tabs


def _diagnose_summary(results: dict, port: int, hosts: List[str]) -> str:
    """Human-facing summary line for diagnostics."""
    all_tabs = results["tabs"]
    open_hosts = [c["host"] for c in results["checks"] if c["port_open"]]
    if not open_hosts:
        return (f"❌ Port {port} not open on any host {hosts}. Chrome not running with "
                f"--remote-debugging-port={port} --user-data-dir=\"C:\\\\arena-images-chrome\". "
                f"Close all Chrome, then run: \"C:\\\\Program Files\\\\Google\\\\Chrome\\\\Application\\\\chrome.exe\" "
                f"--remote-debugging-port={port} --user-data-dir=\"C:\\\\arena-images-chrome\"")
    if not all_tabs:
        return (f"⚠ Port {port} open on {open_hosts} but /json/list returned 0 tabs. Open a page in the "
                f"dedicated Chrome window (the one started with --user-data-dir). If you see Chrome window "
                f"but no tabs, try http://127.0.0.1:{port} in that Chrome to see if DevTools is blocked.")
    return ("✅ Found " + str(len(all_tabs)) + " unique tab(s) on " + str(open_hosts) + ": "
            + "; ".join(f"{t['title'][:40]} — {t['url']}" for t in all_tabs[:3]))


def diagnose_sync(host: str = "127.0.0.1", port: int = 9222) -> dict:
    """Full diagnostics: check port open, /json/version, /json/list on all candidate hosts."""
    results: dict = {"host": host, "port": port, "checks": [], "tabs": [], "summary": ""}
    merged: dict = {}
    for h in hosts_to_try(host):
        check, tabs = _diagnose_host(h, port, preferred_host=host)
        _merge_tabs(merged, tabs, preferred_host=host, first_wins=True)
        results["checks"].append(check)
    all_tabs = list(merged.values())
    results["tabs"] = [{"title": t.title, "url": t.url, "ws_url": t.ws_url, "id": t.id} for t in all_tabs]
    results["summary"] = _diagnose_summary(results, port, hosts_to_try(host))
    return results
