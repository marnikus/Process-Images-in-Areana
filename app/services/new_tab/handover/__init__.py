# ideal-size: 40 lines reason=facade for handover package
from __future__ import annotations
from .main import handover, _run
from .move_close import _GONE_POLL_SEC, _GONE_WAIT_SEC, _close_old, _gone, _move_worker, _roll_back
from .open_prove import _open_and_prove, _prove_new_chat
from .patches import _close_tab_sync, _fetch_tabs_sync, _get_const, _open_tab_sync, _patched, _read_chat_page, _wait_new_chat_ready
from .reconcile import _RECONCILE_WAIT_SEC, _hold_reconciler
from .utils import _connect_all, _log, _quietly

__all__ = ["handover"]
