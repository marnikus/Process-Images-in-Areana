"""CDP tabs — sync fetching + dedup, extracted from cdp_client.py (C2).

RULE18: file 150-300 ideal, func 4-20 LOC, CC≤10, params≤4.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from ..cdp_protocol import (
    TabInfo as _PureTabInfo,
    is_devtools_url as _pure_is_devtools,
    normalize_ws_url as _pure_normalize,
    parse_tabs as _pure_parse_tabs,
    filter_real_tabs as _pure_filter_real,
)


@dataclass
class TabInfo:
    id: str
    title: str
    url: str
    ws_url: str
    type: str = "page"


CANDIDATE_HOSTS = ["127.0.0.1", "localhost"]


def _is_port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _fetch_json_sync(url: str, timeout: float = 3.0) -> Tuple[Any, str]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status} for {url}"
            raw = resp.read()
            try:
                data = json.loads(raw.decode("utf-8", errors="ignore"))
                return data, ""
            except Exception as e:
                return None, f"JSON parse failed for {url}: {e}"
    except urllib.error.URLError as e:
        reason = e.reason if hasattr(e, "reason") else e
        return None, f"URLError {url}: {reason}"
    except Exception as e:
        return None, f"Exception {url}: {e}"


def _normalize_ws_url(ws_url: str, preferred_host: str, preferred_port: int) -> str:
    return _pure_normalize(ws_url, preferred_host, preferred_port)


def _is_devtools_url(url: str, title: str = "") -> bool:
    return _pure_is_devtools(url, title)


def _parse_tabs(items: List[dict], preferred_host: str = "127.0.0.1",
                preferred_port: int = 9222, include_devtools: bool = True) -> List[TabInfo]:
    pure = _pure_parse_tabs(items, preferred_host, preferred_port, include_devtools)
    return [TabInfo(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url, type=t.type) for t in pure]


def _filter_real_tabs(tabs: List[TabInfo]) -> List[TabInfo]:
    pure = [_PureTabInfo(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url, type=t.type) for t in tabs]
    filtered = _pure_filter_real(pure)
    return [TabInfo(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url, type=t.type) for t in filtered]


def _build_hosts_to_try(preferred: str) -> List[str]:
    return [preferred] + [h for h in CANDIDATE_HOSTS if h != preferred]


def _try_fetch_host(host: str, port: int, preferred_host: str, timeout: float) -> Tuple[List[TabInfo], str, str]:
    url = f"http://{host}:{port}/json/list"
    if not _is_port_open(host, port, timeout=1.0):
        err = f"Port {port} not open on {host} — is Chrome running with --remote-debugging-port={port}?"
        return [], err, url
    data, err = _fetch_json_sync(url, timeout=timeout)
    if err:
        return [], err, url
    tabs = _parse_tabs(data, preferred_host=preferred_host, preferred_port=port)
    return tabs, "", url


def _merge_by_id(existing: dict[str, TabInfo], new_tabs: List[TabInfo], preferred_host: str) -> dict[str, TabInfo]:
    for t in new_tabs:
        key = t.id or t.ws_url
        if not key:
            continue
        if key not in existing:
            existing[key] = t
        else:
            cur = existing[key]
            if not cur.ws_url and t.ws_url:
                existing[key] = t
            elif preferred_host in t.ws_url and preferred_host not in cur.ws_url:
                existing[key] = t
    return existing


def fetch_tabs_sync(host: str = "127.0.0.1", port: int = 9222,
                    timeout: float = 3.0) -> Tuple[List[TabInfo], str, List[str]]:
    """Fetch tabs sync, trying candidate hosts, dedup by id."""
    tried: List[str] = []
    last_err = ""
    merged: dict[str, TabInfo] = {}
    for h in _build_hosts_to_try(host):
        tabs, err, url = _try_fetch_host(h, port, host, timeout)
        tried.append(url)
        if err:
            last_err = err
            continue
        _merge_by_id(merged, tabs, host)
    if merged:
        return list(merged.values()), "", tried
    return [], last_err or "No Chrome tabs found", tried


def open_tab_sync(host: str, port: int, url: str, timeout: float = 5.0) -> Tuple[Optional[TabInfo], str]:
    """Open a new tab at `url` (I-79): `PUT /json/new?<percent-encoded url>`.

    Chrome refuses GET (HTTP 405) and decodes the whole query as the URL, so a
    URL with its own `?a=b&c=d` must be percent-encoded (measured, Chromium 131).
    """
    req = urllib.request.Request(f"http://{host}:{port}/json/new?{urllib.parse.quote(url, safe='')}",
                                 method="PUT", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            item = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        return None, f"{type(e).__name__}: {getattr(e, 'reason', e)}"
    tabs = _parse_tabs([item], preferred_host=host, preferred_port=port)
    return (tabs[0], "") if tabs else (None, f"unexpected answer: {str(item)[:80]}")


def close_tab_sync(host: str, port: int, tab_id: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """Close a tab: `/json/close/<id>`; 404 = the tab is already gone (= closed)."""
    try:
        req = urllib.request.Request(f"http://{host}:{port}/json/close/{tab_id}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.read().decode("utf-8", errors="ignore")[:80]
    except urllib.error.HTTPError as e:
        return e.code == 404, f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {getattr(e, 'reason', e)}"


async def _context_of(client: Any, old_id: str) -> Optional[str]:
    """BrowserContextId of old tab, or None for default context."""
    try:
        resp = await client.send("Target.getTargets")
        infos = resp.get("result", {}).get("targetInfos", []) if isinstance(resp, dict) else []
        if not infos:
            infos = resp.get("targetInfos", []) if isinstance(resp, dict) else []
        for info in infos:
            if info.get("targetId") == old_id:
                return info.get("browserContextId")
    except Exception:
        return None
    return None


async def open_tab_in_same_context(client: Any, host: str, port: int, url: str, old_id: str) -> Tuple[Optional[TabInfo], str]:
    """Open new tab in same browser context as old_id (profile-correct, keeps Arena account)."""
    ctx_id = await _context_of(client, old_id)
    params = {"url": url}
    if ctx_id:
        params["browserContextId"] = ctx_id
    try:
        resp = await client.send("Target.createTarget", params)
        result = resp.get("result", resp) if isinstance(resp, dict) else {}
        new_id = result.get("targetId", "")
        if not new_id:
            return None, f"createTarget no id {str(resp)[:120]}"
        # Fetch to get ws_url
        import asyncio as _asyncio
        tabs, err, _ = await _asyncio.to_thread(fetch_tabs_sync, host, port)
        if err:
            return TabInfo(id=new_id, title="", url=url, ws_url=f"ws://{host}:{port}/devtools/page/{new_id}"), ""
        for tab in tabs:
            if tab.id == new_id:
                return tab, ""
        return TabInfo(id=new_id, title="", url=url, ws_url=f"ws://{host}:{port}/devtools/page/{new_id}"), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
