"""RDP session — tabs, console actors and the click/probe verbs.

The actor tree is the API: `root` → `listTabs` → a tab descriptor →
`getTarget` → that target's `consoleActor` → `evaluateJSAsync`.

**Actor ids are per-connection and must never be cached across one.** Firefox
hands out `server1.conn21.tabDescriptor7`, and the `conn21` part changes on
every attach, so a reconnect re-enumerates from `root` instead of reusing what
it learned last time. `FirefoxTab` is therefore a value object (id + title +
url), never a live handle.

`evaluateJSAsync` answers twice: an immediate ack carrying `resultID`, then a
separate `evaluationResult` **event** with the value. Reading the ack as the
result is the classic bug — `evaluate` waits for the matching event.

Layer: browser leaf — transport + JS builders only; no Qt, no app imports.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .click_js import build_click_js, build_probe_js, build_webdriver_probe_js
from .transport import RDPClosed, RDPTransport

__all__ = ["FirefoxTab", "RDPSession", "ClickResult"]

_EVENT_POLL_S = 0.02


@dataclass(frozen=True)
class FirefoxTab:
    """One open tab as the pool sees it (ids are valid for this connection only)."""

    actor: str
    title: str
    url: str
    selected: bool = False


@dataclass(frozen=True)
class ClickResult:
    """Outcome of a click/probe: `ok` plus a human reason when it did not happen."""

    ok: bool
    reason: str = ""
    detail: Dict[str, Any] = None  # type: ignore[assignment]


class RDPSession:
    """Attach → list tabs → click, with every actor re-resolved per connection."""

    def __init__(self, transport: Optional[RDPTransport] = None):
        self.transport = transport or RDPTransport()
        self._console_by_tab: Dict[str, str] = {}

    @property
    def is_attached(self) -> bool:
        return self.transport.is_connected

    async def attach(self) -> Dict[str, Any]:
        """Open the connection; the cache of actor ids starts empty (they are per-connection)."""
        self._console_by_tab = {}
        return await self.transport.connect()

    async def detach(self) -> None:
        """Release the browser without closing it — reattach whenever."""
        self._console_by_tab = {}
        await self.transport.close()

    async def list_tabs(self) -> List[FirefoxTab]:
        """Every open tab, newest actor ids (`root` → `listTabs`)."""
        reply = await self.transport.request({"to": "root", "type": "listTabs"})
        return [FirefoxTab(actor=str(t.get("actor", "")),
                           title=str(t.get("title", "")),
                           url=str(t.get("url", "")),
                           selected=bool(t.get("selected", False)))
                for t in reply.get("tabs", []) or [] if t.get("actor")]

    async def console_actor(self, tab: FirefoxTab) -> str:
        """The tab's console actor (`getTarget`), memoised for this connection only."""
        cached = self._console_by_tab.get(tab.actor)
        if cached:
            return cached
        reply = await self.transport.request({"to": tab.actor, "type": "getTarget"})
        target = reply.get("frame") or reply.get("target") or reply
        actor = str(target.get("consoleActor", "") or "")
        if not actor:
            raise RDPClosed(f"tab {tab.actor} exposed no console actor")
        self._console_by_tab[tab.actor] = actor
        return actor

    async def evaluate(self, tab: FirefoxTab, expression: str) -> Any:
        """Run JS in the page and return its value (ack first, then the event)."""
        console = await self.console_actor(tab)
        ack = await self.transport.request(
            {"to": console, "type": "evaluateJSAsync", "text": expression})
        result_id = ack.get("resultID")
        if not result_id:
            return _grip_value(ack.get("result"))
        return _grip_value(await self._await_result(console, str(result_id)))

    async def click(self, tab: FirefoxTab, selector: str) -> ClickResult:
        """Click the first match: a miss is a reason, never an exception (RULE 4)."""
        return _as_result(await self.evaluate(tab, build_click_js(selector)))

    async def probe(self, tab: FirefoxTab, selector: str) -> ClickResult:
        """Does the element exist and is it laid out? No interaction."""
        return _as_result(await self.evaluate(tab, build_probe_js(selector)))

    async def automation_signals(self, tab: FirefoxTab) -> Dict[str, bool]:
        """What the *site* sees — `{'webdriver': False, 'hasCdc': False}` when clean (I-62)."""
        raw = _as_result(await self.evaluate(tab, build_webdriver_probe_js()))
        found = raw.detail or {}
        return {"webdriver": bool(found.get("webdriver")),
                "hasCdc": bool(found.get("hasCdc"))}

    async def _await_result(self, console: str, result_id: str) -> Any:
        """Wait for the `evaluationResult` event carrying our `resultID`."""
        deadline = asyncio.get_event_loop().time() + self.transport.timeout
        while asyncio.get_event_loop().time() < deadline:
            for event in self.transport.drain_events():
                if _is_our_result(event, console, result_id):
                    return event.get("result")
            await asyncio.sleep(_EVENT_POLL_S)
        raise RDPClosed(f"no evaluationResult for {result_id} in {self.transport.timeout}s")


def _is_our_result(event: Dict[str, Any], console: str, result_id: str) -> bool:
    """The `evaluationResult` for this exact evaluation."""
    return (event.get("type") == "evaluationResult" and event.get("from") == console
            and str(event.get("resultID", "")) == result_id)


def _grip_value(result: Any) -> Any:
    """Unwrap a console grip to a plain value (our payloads always return strings)."""
    if isinstance(result, dict):
        if result.get("type") == "undefined":
            return None
        return result.get("value", result)
    return result


def _as_result(raw: Any) -> ClickResult:
    """Parse a payload's JSON answer; anything unexpected is broken, not empty."""
    if not isinstance(raw, str):
        return ClickResult(ok=False, reason=f"no answer from page ({type(raw).__name__})", detail={})
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ClickResult(ok=False, reason=f"unparsable answer: {raw[:60]}", detail={})
    return ClickResult(ok=bool(data.get("ok")), reason=str(data.get("reason", "")), detail=data)
