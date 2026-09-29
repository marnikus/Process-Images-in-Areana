# ideal-size: 35 lines reason=facade for tabs package, keeps urllib attr for legacy tests
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from .context import _context_of, open_tab_in_same_context
from .fetch import (
    _build_hosts_to_try,
    _fetch_json_sync,
    _filter_real_tabs,
    _is_devtools_url,
    _is_port_open,
    _merge_by_id,
    _normalize_ws_url,
    _parse_tabs,
    _try_fetch_host,
    fetch_tabs_sync,
)
from .models import CANDIDATE_HOSTS, TabInfo
from .open_close import close_tab_sync, open_tab_sync

__all__ = [
    "TabInfo",
    "CANDIDATE_HOSTS",
    "fetch_tabs_sync",
    "open_tab_sync",
    "close_tab_sync",
    "open_tab_in_same_context",
    "_is_port_open",
    "_fetch_json_sync",
    "_normalize_ws_url",
    "_is_devtools_url",
    "_parse_tabs",
    "_filter_real_tabs",
]
