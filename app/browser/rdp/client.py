"""RDP client — attach, list tabs, evaluate, click (2026-09-21, round 8).

One attach = one socket = one actor tree. Firefox renames every actor when the
connection opens (`server1.connN.…`), so the client resolves the tab's console
actor **per operation** and retries once when the browser answers
`noSuchActor` (design D-2) — that is what lets the app detach and re-attach
without ever touching the running browser.

Everything public here has the same failure shape as the CDP/BiDi paths in this
codebase: `(value, reason)` and never an exception, because these calls run
inside Qt slots. The class is the seam the tests drive; the module-level
functions are what `endpoints` and the panel call.

RULE 18: class ≤150 LOC / ≤15 methods; funcs ≤20; ≤3 params.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

from . import actors
from .actors import click_expression
from .connection import RdpConnection
from .wire import (DEFAULT_TIMEOUT, GREETING_TIMEOUT, PROTOCOL, Endpoint, RdpError,
                   tab_handle)

RESULT_LIMIT = 4096      # long-string chunk we ask for when the reply has no length
ASYNC_COMMAND = "evaluateJSAsync"
LEGACY_COMMAND = "evaluateJS"


def _long_text(connection: RdpConnection, reply: dict, timeout) -> str:
    """A long string's full text via its own actor (the head when that fails)."""
    actor = str(actors.result_grip(reply).get("actor") or "")
    if not actor:
        return actors.initial_text(reply)
    packet = {"to": actor, "type": "substring", "start": 0,
              "end": actors.total_length(reply) or RESULT_LIMIT}
    try:
        return actors.substring_text(connection.request(packet, timeout)) or actors.initial_text(reply)
    except RdpError:
        return actors.initial_text(reply)


def probe(point: Endpoint, timeout: float = GREETING_TIMEOUT) -> bool:
    """Does an RDP server greet us here? Used by protocol detection (never raises)."""
    connection = RdpConnection(point, timeout=timeout)
    try:
        connection.connect()
        return bool(connection.greeting)
    except (RdpError, OSError):
        return False
    finally:
        connection.close()


class RdpClient:
    """A connection to one running Firefox's DevTools server."""

    def __init__(self, endpoint: Endpoint, timeout: float = DEFAULT_TIMEOUT,
                 opener: Optional[Callable] = None) -> None:
        self._endpoint = endpoint
        self._timeout = float(timeout)
        self._connection = RdpConnection(endpoint, timeout, opener)
        self._actor_cache: Dict[str, str] = {}
        self._async_known: Optional[bool] = None

    # ── lifecycle (attach / detach: the browser is never touched) ─────────

    def __enter__(self) -> "RdpClient":
        return self.connect()

    def __exit__(self, *_exc) -> bool:
        self.close()
        return False

    def connect(self) -> "RdpClient":
        """Open the socket and read the greeting."""
        self._connection.connect()
        return self

    def close(self) -> None:
        """Drop the socket (idempotent); Firefox keeps running with every tab open."""
        self._connection.close()

    # ── tabs (identity = browsingContextID, handle = ctx-N) ──────────────

    def tabs(self, timeout=None) -> List[actors.RdpTab]:
        """Every open tab; the same `ctx-N` ids across reconnects."""
        reply = self._connection.request({"to": "root", "type": "listTabs"}, timeout)
        return [replace(t, ws_url=tab_handle(self._endpoint, t.id)) for t in actors.tabs_in(reply)]

    def select(self, tab_id: str, timeout=None) -> actors.RdpTab:
        """The tab with this handle id, or a named error listing what is open."""
        want = str(tab_id or "")
        rows = self.tabs(timeout)
        for tab in rows:
            if tab.id == want:
                return tab
        open_ids = ", ".join(t.id for t in rows) or "none"
        raise RdpError(f"no tab {want!r} — Firefox lists: {open_ids}", "protocol")

    def info(self) -> dict:
        """What this DevTools server says about itself (greeting + tab count)."""
        greeting = self._connection.greeting or {}
        return {"application": str(greeting.get("applicationType") or ""),
                "prefix": str(greeting.get("testConnectionPrefix") or ""),
                "traits": dict(greeting.get("traits") or {}),
                "tabs": len(self.tabs()), "protocol": PROTOCOL,
                "host": self._endpoint.host, "port": int(self._endpoint.port)}

    # ── JS (the only action this channel offers — design R2/R3) ──────────

    def evaluate(self, tab_id: str, expression: str, timeout=None) -> dict:
        """Run JS in a tab; one stale-actor retry, never a loop."""
        tab = self.select(tab_id, timeout)
        try:
            return self._eval_once(tab, expression, timeout)
        except RdpError as e:
            if e.kind != "noSuchActor":
                raise
            self._actor_cache.pop(tab.id, None)
            return self._eval_once(tab, expression, timeout)

    def value_of(self, reply: dict, timeout=None) -> Tuple[object, str]:
        """The JS value of an evaluation reply, long strings resolved."""
        error = actors.exception_text(reply)
        if error:
            return None, error
        if actors.is_long_string(reply):
            text = _long_text(self._connection, reply, timeout)
        else:
            text = actors.string_value(reply)
        if text is None:
            return actors.result_grip(reply).get("value"), ""
        try:
            return json.loads(text), ""
        except ValueError:
            return text, ""

    def click(self, tab_id: str, selector: str, timeout=None) -> Tuple[bool, str]:
        """Click one element in the page (`el.click()`), reporting why not."""
        reply = self.evaluate(tab_id, click_expression(selector), timeout)
        value, error = self.value_of(reply, timeout)
        if error:
            return False, error
        verdict = value if isinstance(value, dict) else actors.click_verdict(reply)
        if verdict.get("ok"):
            return True, ""
        return False, str(verdict.get("why") or "the page did not confirm the click")

    # ── actor resolution ─────────────────────────────────────────────────

    def _eval_once(self, tab: actors.RdpTab, expression: str, timeout) -> dict:
        """One evaluation — the async command when this server knows it, else legacy.

        `requestTypes` answers which packet types the actor implements, is asked
        once per attach, and is what keeps this working on servers that predate
        `evaluateJSAsync` (they answer the async packet with an error otherwise).
        """
        console = self._console_actor(tab, timeout)
        if self._async_known is None:
            names = actors.actor_types(self._connection.request(
                {"to": console, "type": "requestTypes"}, timeout))
            self._async_known = ASYNC_COMMAND in names
        command = ASYNC_COMMAND if self._async_known else LEGACY_COMMAND
        reply = self._connection.request({"to": console, "type": command,
                                          "text": str(expression)}, timeout)
        if not self._async_known:
            return reply
        return self._await_result(console, actors.result_id(reply), timeout)

    def _console_actor(self, tab: actors.RdpTab, timeout) -> str:
        """The tab's console actor (cached per attach — actors die with the socket)."""
        cached = self._actor_cache.get(tab.id)
        return cached or self._resolve_console(tab, timeout)

    def _resolve_console(self, tab: actors.RdpTab, timeout) -> str:
        """`getTarget` on the descriptor; `attach` when the form hides the actor."""
        form = actors.target_form(self._connection.request(
            {"to": tab.actor, "type": "getTarget"}, timeout))
        console = actors.console_actor_of(form)
        if not console:
            attached = self._connection.request({"to": tab.actor, "type": "attach"}, timeout)
            console = actors.console_actor_of(actors.target_form(attached))
        self._actor_cache[tab.id] = actors.require_actor(console)
        return self._actor_cache[tab.id]

    def _await_result(self, console: str, result_id: str, timeout) -> dict:
        """The `evaluationResult` event that answers an async evaluation."""
        if not result_id:
            raise RdpError(f"{console} answered without a resultID", "protocol")
        return self._connection.wait_for(lambda p: actors.result_matches(p, result_id), timeout)


@contextmanager
def attach(point: Endpoint, timeout: float = DEFAULT_TIMEOUT):
    """A connected client for one operation, closed again whatever happens."""
    client = RdpClient(point, timeout)
    client.connect()
    try:
        yield client
    finally:
        client.close()


def list_targets(point: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> Tuple[List[actors.RdpTab], str]:
    """Every tab of this Firefox, or ([] + why) — never raises."""
    try:
        with attach(point, timeout) as client:
            return client.tabs(timeout), ""
    except RdpError as e:
        return [], str(e)


def evaluate_json(point: Endpoint, tab_id: str, expression: str, timeout: float = DEFAULT_TIMEOUT):
    """Evaluate JS and return the parsed value, or (None + why)."""
    try:
        with attach(point, timeout) as client:
            reply = client.evaluate(tab_id, expression, timeout)
            return client.value_of(reply, timeout)
    except RdpError as e:
        return None, str(e)


def click(point: Endpoint, tab_id: str, selector: str, timeout: float = DEFAULT_TIMEOUT):
    """Click one element (True + "" when it happened, else False + why)."""
    try:
        with attach(point, timeout) as client:
            return client.click(tab_id, selector, timeout)
    except RdpError as e:
        return False, str(e)


def session_info(point: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> Tuple[dict, str]:
    """Greeting + tab count of one DevTools server, or ({} + why)."""
    try:
        with attach(point, timeout) as client:
            return client.info(), ""
    except RdpError as e:
        return {}, str(e)
