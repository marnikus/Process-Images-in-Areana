# ideal-size: 120 lines reason=facade re-exports new-tab handover package for backward compat, one public API per RULE 10
"""New-tab handover package — facade (split from single 668 LOC file).

Public API preserved:
- SETTING_KEY, URL_KEY, DEFAULT_URL
- clean_url, read_setting, save_setting, wanted_url
- handover
- For tests: open_tab_sync, close_tab_sync, fetch_tabs_sync, wait_new_chat_ready, read_chat_page, _GONE_POLL_SEC, _GONE_WAIT_SEC, _RECONCILE_WAIT_SEC, _Move, _plan, etc.

Implementation split into focused modules:
- settings.py, move.py, matching.py, storage.py, cookies.py, context.py, owner.py, handover.py
"""

from __future__ import annotations

from app.browser.cdp.tabs import close_tab_sync as _real_close
from app.browser.cdp.tabs import fetch_tabs_sync as _real_fetch
from app.browser.cdp.tabs import open_tab_sync as _real_open
from app.browser.chat_page import read_chat_page as _real_read
from app.browser.new_chat import wait_new_chat_ready as _real_wait

from .cookies import (
    _cookie_base,
    _cookie_params,
    _get_cookies_from_move,
    _reload_after_cookies,
    _set_cookies_to_move,
    _set_one_cookie,
)
from .context import (
    _context_from_targets,
    _get_new_context_id,
    _get_old_context_id,
    _pick_client_for_context,
    _try_open_same_context,
    _verify_context_same,
)
from .handover import (
    _GONE_POLL_SEC,
    _GONE_WAIT_SEC,
    _RECONCILE_WAIT_SEC,
    _close_old,
    _connect_all,
    _gone,
    _hold_reconciler,
    _log,
    _move_worker,
    _open_and_prove,
    _prove_new_chat,
    _quietly,
    _roll_back,
    _run,
    handover,
)
from .matching import (
    _count_profile_tabs,
    _count_profile_tabs_by_owner,
    _endpoint_from_client,
    _endpoint_matches,
    _get_pattern,
    _matches_pattern,
    _owner_matches,
)
from .move import _Move, _clients_on, _plan, _resolve_endpoint
from .owner import (
    _check_owner_preserved,
    _preserve_owner_after_move,
    _read_owner_from_client,
)
from .settings import (
    DEFAULT_URL,
    SETTING_KEY,
    URL_KEY,
    clean_url,
    read_setting,
    save_setting,
    wanted_url,
)
from .storage import _get_storage_from_move, _set_storage_to_move

# Real implementations exposed for monkeypatching in tests
open_tab_sync = _real_open
close_tab_sync = _real_close
fetch_tabs_sync = _real_fetch
wait_new_chat_ready = _real_wait
read_chat_page = _real_read

__all__ = [
    "SETTING_KEY",
    "URL_KEY",
    "DEFAULT_URL",
    "clean_url",
    "read_setting",
    "save_setting",
    "wanted_url",
    "handover",
    "open_tab_sync",
    "close_tab_sync",
    "fetch_tabs_sync",
    "wait_new_chat_ready",
    "read_chat_page",
    "_GONE_POLL_SEC",
    "_GONE_WAIT_SEC",
    "_RECONCILE_WAIT_SEC",
    "_Move",
    "_plan",
    "_clients_on",
    "_resolve_endpoint",
    "_endpoint_from_client",
    "_get_pattern",
    "_matches_pattern",
    "_endpoint_matches",
    "_owner_matches",
    "_count_profile_tabs",
    "_count_profile_tabs_by_owner",
    "_get_storage_from_move",
    "_set_storage_to_move",
    "_pick_client_for_context",
    "_get_cookies_from_move",
    "_set_cookies_to_move",
    "_cookie_base",
    "_cookie_params",
    "_set_one_cookie",
    "_reload_after_cookies",
    "_verify_context_same",
    "_context_from_targets",
    "_get_old_context_id",
    "_get_new_context_id",
    "_try_open_same_context",
    "_read_owner_from_client",
    "_check_owner_preserved",
    "_preserve_owner_after_move",
    "_hold_reconciler",
    "_run",
    "_open_and_prove",
    "_prove_new_chat",
    "_connect_all",
    "_roll_back",
    "_move_worker",
    "_close_old",
    "_gone",
    "_quietly",
    "_log",
]
