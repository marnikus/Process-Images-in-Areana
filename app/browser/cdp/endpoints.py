"""CDP HTTP endpoints — port probes and JSON fetches (W2 split from cdp_client)."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, List, Tuple

CANDIDATE_HOSTS = ["127.0.0.1", "localhost"]


def hosts_to_try(host: str) -> List[str]:
    """Preferred host first, then other candidates, deduplicated."""
    return [host] + [h for h in CANDIDATE_HOSTS if h != host]


def is_port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    """TCP connect probe against host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def fetch_json_sync(url: str, timeout: float = 3.0) -> Tuple[Any, str]:
    """GET url expecting JSON -> (data, "") or (None, error message)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status} for {url}"
            return _decode_json(url, resp.read())
    except urllib.error.URLError as e:
        return None, f"URLError {url}: {e.reason if hasattr(e, 'reason') else e}"
    except Exception as e:
        return None, f"Exception {url}: {e}"


def _decode_json(url: str, raw: bytes) -> Tuple[Any, str]:
    """Decode response body as JSON -> (data, "") or (None, error)."""
    try:
        return json.loads(raw.decode("utf-8", errors="ignore")), ""
    except Exception as e:
        return None, f"JSON parse failed for {url}: {e}"
