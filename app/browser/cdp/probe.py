"""CDP probe — diagnose_sync extracted (C2).

RULE18: file 150-300, func ≤20 LOC, CC≤10.
"""
from __future__ import annotations

from typing import List

from .tabs import (
    TabInfo,
    CANDIDATE_HOSTS,
    _build_hosts_to_try,
    _is_port_open,
    _fetch_json_sync,
    _parse_tabs,
)


def _check_single_host(host: str, port: int, preferred_host: str) -> dict:
    check = {
        "host": host,
        "port_open": False,
        "version": None,
        "version_error": "",
        "list_count": 0,
        "list_error": "",
        "tabs": [],
    }
    check["port_open"] = _is_port_open(host, port, timeout=1.0)
    v_url = f"http://{host}:{port}/json/version"
    v_data, v_err = _fetch_json_sync(v_url, timeout=2.0)
    if v_err:
        check["version_error"] = v_err
    else:
        check["version"] = v_data
    l_url = f"http://{host}:{port}/json/list"
    l_data, l_err = _fetch_json_sync(l_url, timeout=3.0)
    if l_err:
        check["list_error"] = l_err
    else:
        tabs = _parse_tabs(l_data, preferred_host=preferred_host, preferred_port=port)
        check["list_count"] = len(tabs)
        check["tabs"] = [{"title": t.title[:80], "url": t.url, "id": t.id} for t in tabs[:10]]
    return check


def _collect_all_tabs(checks: List[dict], raw_tabs_by_host: dict) -> List[TabInfo]:
    merged: dict[str, TabInfo] = {}
    for host, tabs in raw_tabs_by_host.items():
        for t in tabs:
            key = t.id or t.ws_url
            if key and key not in merged:
                merged[key] = t
    return list(merged.values())


def _build_summary(checks: List[dict], all_tabs: List[TabInfo], port: int, hosts_tried: List[str]) -> str:
    open_hosts = [c["host"] for c in checks if c["port_open"]]
    if not open_hosts:
        return (
            f"❌ Port {port} not open on any host {hosts_tried}. "
            f"Chrome not running with --remote-debugging-port={port} "
            f'--user-data-dir="C:\\\\arena-images-chrome".'
        )
    if not all_tabs:
        return (
            f"⚠ Port {port} open on {open_hosts} but /json/list returned 0 tabs. "
            f"Open a page in the dedicated Chrome window."
        )
    sample = "; ".join(f"{t.title[:40]} — {t.url}" for t in all_tabs[:3])
    return f"✅ Found {len(all_tabs)} unique tab(s) on {open_hosts}: {sample}"


def _fetch_tabs_for_probe(host: str, port: int, preferred_host: str) -> List[TabInfo]:
    l_url = f"http://{host}:{port}/json/list"
    l_data, l_err = _fetch_json_sync(l_url, timeout=3.0)
    if l_err:
        return []
    return _parse_tabs(l_data, preferred_host=preferred_host, preferred_port=port)


def diagnose_sync(host: str = "127.0.0.1", port: int = 9222) -> dict:
    """Full diagnostics across candidate hosts."""
    results = {"host": host, "port": port, "checks": [], "tabs": [], "summary": ""}
    hosts_to_try = _build_hosts_to_try(host)
    raw_by_host: dict[str, List[TabInfo]] = {}
    for h in hosts_to_try:
        chk = _check_single_host(h, port, host)
        results["checks"].append(chk)
        raw_by_host[h] = _fetch_tabs_for_probe(h, port, host)
    all_tabs = _collect_all_tabs(results["checks"], raw_by_host)
    results["tabs"] = [
        {"title": t.title, "url": t.url, "ws_url": t.ws_url, "id": t.id} for t in all_tabs
    ]
    results["summary"] = _build_summary(results["checks"], all_tabs, port, hosts_to_try)
    return results
