"""Page restart — open a fresh New Chat by navigating the tab (2026-09-27 D-4).

When the New Chat click or its load wait fails, the tab is navigated to its
own origin + the New Chat link's href (`NEW_CHAT_PATH`, site_adapter). That is
the page the click would have opened, on the same user-authorized origin
(RULE 20). The URL comes from `Target.getTargetInfo`, which the browser
answers even when the page's JS is stuck.

Proven in real Chromium (design §5):
* a leave-page dialog holds the navigate open, so it is accepted after
  DIALOG_GRACE_S;
* a renderer stuck in a script ignores the navigate, so the script is
  terminated (`Runtime.terminateExecution`) and the navigate is tried once
  more.

Imports: probe_selectors only (same layer).
"""

from __future__ import annotations

import asyncio
from typing import Any, Tuple
from urllib.parse import urlsplit

from .probe_selectors import new_chat_path

NAV_TIMEOUT_S = 15.0
INFO_TIMEOUT_S = 5.0
DIALOG_GRACE_S = 1.5


def _body(reply: Any) -> dict:
    """A raw CDP reply → its result; a CDP error becomes {'errorText': message}."""
    if not isinstance(reply, dict):
        return {}
    if reply.get("error"):
        err = reply["error"]
        return {"errorText": str(err.get("message") if isinstance(err, dict) else err)}
    body = reply.get("result", reply)
    return body if isinstance(body, dict) else {}


async def tab_url(cdp: Any) -> str:
    """The tab's URL from the browser side; '' when unknown."""
    try:
        body = _body(await cdp.send("Target.getTargetInfo", {}, timeout=INFO_TIMEOUT_S))
    except Exception:
        return ""
    return str((body.get("targetInfo") or {}).get("url") or "")


def new_chat_url(url: str) -> str:
    """origin + NEW_CHAT_PATH for an http(s) tab URL; '' otherwise."""
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}{new_chat_path()}"


async def _navigate(cdp: Any, url: str) -> str:
    """'' when the browser accepted the navigate, else why not."""
    try:
        body = _body(await cdp.send("Page.navigate", {"url": url}, timeout=NAV_TIMEOUT_S))
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return str(body.get("errorText") or "")


async def _quiet_send(cdp: Any, method: str, params: dict) -> None:
    """Best-effort command whose failure means 'nothing to do' (no dialog, no script)."""
    try:
        await cdp.send(method, params, timeout=INFO_TIMEOUT_S)
    except Exception:
        pass


async def _navigate_past_dialog(cdp: Any, url: str) -> str:
    """Navigate; a navigate still open after DIALOG_GRACE_S gets its leave-page dialog accepted."""
    nav = asyncio.ensure_future(_navigate(cdp, url))
    done, _ = await asyncio.wait({nav}, timeout=DIALOG_GRACE_S)
    if not done:
        await _quiet_send(cdp, "Page.handleJavaScriptDialog", {"accept": True})
    return await nav


async def restart_to_new_chat(cdp: Any) -> Tuple[bool, str]:
    """Navigate the tab to its origin's New Chat page: (ok, url) or (False, why)."""
    url = new_chat_url(await tab_url(cdp))
    if not url:
        return False, "the tab's address is unknown"
    why = await _navigate_past_dialog(cdp, url)
    if why:
        await _quiet_send(cdp, "Runtime.terminateExecution", {})  # a script holding the renderer
        why = await _navigate_past_dialog(cdp, url)
    return (True, url) if not why else (False, f"{url}: {why}")
