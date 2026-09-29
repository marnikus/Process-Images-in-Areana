"""One endpoint's browser as CDP sees it — dial, target list, create, close (I-79 v5).

Why a dedicated connection: `Target.getTargets`, `Target.createTarget` and `Target.closeTarget`
are **browser-level** commands; a page/session socket answers them with "Not allowed". A fresh
`/json/version` → `webSocketDebuggerUrl` socket is the only place where a profile's
`browserContextId` becomes readable, and therefore the only place where "which profile is this
tab in?" can be answered instead of guessed (RULE 16 / I-79 v5).

RULE 18: file 150-300 ideal, func 4-20 LOC, params ≤4. Imports: cdp.transport + cdp_protocol.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .client import CDPClient

log = logging.getLogger("arena")

_WS_RE = re.compile(r"ws://([^:/]+):(\d+)/")
_PAGE = "page"
_VERSION_TIMEOUT_SEC = 3.0


def endpoint_of_ws(ws_url: str | None) -> tuple[str, int] | None:
    """`ws://host:port/devtools/…` → `(host, port)`; `None` when the socket is unreadable.

    The endpoint of a job is the endpoint of **its own tab's socket** — never a pool or client
    default (P1).
    """
    if not isinstance(ws_url, str):
        return None
    found = _WS_RE.match(ws_url)
    return (found.group(1), int(found.group(2))) if found else None


def context_of(target_infos: list[dict], target_id: str) -> str | None:
    """The browser context of one page; `""` = the default profile, `None` = not listed.

    `None` must never collapse into `""` (P2): "not in this browser" and "the default profile"
    are different answers, and only one of them allows a handover.
    """
    page = target_of(target_infos, target_id)
    if page is None:
        return None
    ctx = page.get("browserContextId")
    return ctx if isinstance(ctx, str) else ""


def target_of(target_infos: list[dict], target_id: str) -> dict | None:
    """The page target with that id, or `None` when this browser does not list one."""
    for info in target_infos:
        if info.get("targetId") == target_id and info.get("type", _PAGE) == _PAGE:
            return info
    return None


def matching_targets(target_infos: list[dict], needle: str, context_id: str | None = None) -> list[dict]:
    """Page targets whose URL contains `needle` (and, when given, whose context matches)."""
    if not needle:
        return []
    found = []
    for info in target_infos:
        if info.get("type", _PAGE) != _PAGE or needle not in str(info.get("url") or ""):
            continue
        if context_id is not None and context_of(target_infos, info.get("targetId")) != context_id:
            continue
        found.append(info)
    return found


def _browser_ws_url(host: str, port: int) -> str:
    """Read `/json/version` — the endpoint's *browser* socket (page sockets cannot Target.*)."""
    from .tabs import _fetch_json_sync                    # same layer, private by design
    data, err = _fetch_json_sync(f"http://{host}:{port}/json/version", _VERSION_TIMEOUT_SEC)
    if not isinstance(data, dict):
        log.info(f"browser_targets: no /json/version at {host}:{port} ({err})")
        return ""
    return str(data.get("webSocketDebuggerUrl") or "")


def _reply(result: dict, method: str) -> tuple[dict, str]:
    """Chrome's answer → `(result, "")` or `({}, why)`; a bare dict is treated as a result."""
    if not isinstance(result, dict):
        return {}, f"{method} answered {type(result).__name__}"
    error = result.get("error")
    if error:
        return {}, f"{method}: {error.get('message') if isinstance(error, dict) else error}"
    payload = result.get("result")
    return (payload if isinstance(payload, dict) else {}), ""


@dataclass
class BrowserTargets:
    """An open browser-level connection to one endpoint; every call returns a reason, no raises."""

    host: str
    port: int
    client: object
    _closed: bool = False

    async def targets(self) -> tuple[list[dict], str]:
        """Every target of this browser — all profiles — or `([], why)`.

        `[]` must be treated as "the browser did not answer" by callers, never as "no tabs"
        (silent endpoint ≠ empty browser).
        """
        try:
            payload, err = _reply(await self.client.send("Target.getTargets"), "Target.getTargets")
        except Exception as exc:                          # socket gone mid-handover
            return [], str(exc)
        infos = payload.get("targetInfos") if err == "" else None
        if not isinstance(infos, list):
            return [], err or "Target.getTargets answered no targetInfos"
        return [i for i in infos if isinstance(i, dict)], ""

    async def create(self, url: str, context_id: str = "") -> tuple[str, str]:
        """`Target.createTarget` in that context; `("", why)` when the browser refuses.

        A regular Chrome profile always refuses (design §4) — that refusal is a reason to try
        the page opener, not an error to swallow.
        """
        params: dict = {"url": url}
        if context_id:
            params["browserContextId"] = context_id
        try:
            payload, err = _reply(await self.client.send("Target.createTarget", params), "Target.createTarget")
        except Exception as exc:
            return "", str(exc)
        target_id = payload.get("targetId") if err == "" else None
        return (str(target_id), "") if target_id else ("", err or "Target.createTarget answered no id")

    async def close(self, target_id: str) -> tuple[bool, str]:
        """`Target.closeTarget`; the caller still proves the absence with a fresh target list (P4)."""
        try:
            payload, err = _reply(await self.client.send("Target.closeTarget", {"targetId": target_id}),
                                  "Target.closeTarget")
        except Exception as exc:
            return False, str(exc)
        if err:
            return False, err
        return (True, "") if payload.get("success", True) else (False, "the browser refused the close")

    async def aclose(self) -> None:
        """Close the connection; failures are logged, never raised (a handover must not crash)."""
        if self._closed:
            return
        self._closed = True
        try:
            await self.client.disconnect()
        except Exception as exc:
            log.info(f"browser_targets: disconnect failed for {self.host}:{self.port}: {exc}")


async def dial(host: str, port: int, timeout_sec: float = 5.0) -> tuple[BrowserTargets | None, str]:
    """Connect to the browser websocket of one endpoint; `(browser, "")` or `(None, why)`."""
    ws_url = _browser_ws_url(host, port)
    if not ws_url:
        return None, f"no browser websocket at {host}:{port} (/json/version)"
    client = CDPClient(host, port)
    try:
        if not await client.connect(ws_url):
            return None, f"browser websocket refused at {host}:{port}"
    except Exception as exc:
        return None, f"browser websocket failed at {host}:{port}: {exc}"
    log.info(f"browser_targets: connected to the browser of {host}:{port}")
    return BrowserTargets(host=host, port=port, client=client), ""
