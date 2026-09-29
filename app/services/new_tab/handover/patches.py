from __future__ import annotations
import sys
from app.browser.cdp.tabs import close_tab_sync as _real_close
from app.browser.cdp.tabs import fetch_tabs_sync as _real_fetch
from app.browser.cdp.tabs import open_tab_sync as _real_open
from app.browser.chat_page import read_chat_page as _real_read
from app.browser.new_chat import wait_new_chat_ready as _real_wait

def _patched(name: str, default):
    try:
        mod = sys.modules.get("app.services.new_tab")
        if mod is not None and hasattr(mod, name):
            val = getattr(mod, name)
            if val is not default or name in mod.__dict__:
                return val
    except Exception:
        pass
    return default

def _open_tab_sync(*args, **kwargs):
    fn = _patched("open_tab_sync", _real_open)
    return fn(*args, **kwargs)

def _close_tab_sync(*args, **kwargs):
    fn = _patched("close_tab_sync", _real_close)
    return fn(*args, **kwargs)

def _fetch_tabs_sync(*args, **kwargs):
    fn = _patched("fetch_tabs_sync", _real_fetch)
    return fn(*args, **kwargs)

async def _wait_new_chat_ready(*args, **kwargs):
    fn = _patched("wait_new_chat_ready", _real_wait)
    return await fn(*args, **kwargs)

async def _read_chat_page(*args, **kwargs):
    fn = _patched("read_chat_page", _real_read)
    return await fn(*args, **kwargs)

def _get_const(name: str, default: float) -> float:
    try:
        mod = sys.modules.get("app.services.new_tab")
        if mod is not None and hasattr(mod, name):
            return float(getattr(mod, name))
    except Exception:
        pass
    return default
