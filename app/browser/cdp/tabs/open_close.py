from __future__ import annotations

import json
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional, Tuple

from .fetch import _parse_tabs
from .models import TabInfo


def open_tab_sync(host: str, port: int, url: str, timeout: float = 5.0) -> Tuple[Optional[TabInfo], str]:
    """Open a new tab at `url` (I-79): `PUT /json/new?<percent-encoded url>`."""
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
