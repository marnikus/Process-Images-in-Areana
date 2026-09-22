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

Round 11: the module-level functions and `attached` no longer open a socket each —
they take the **one** socket `session` keeps for this endpoint (fifteen connections per
pass was fifteen permission dialogs; see `session.py`).

RULE 18: class ≤150 LOC / ≤15 methods; funcs ≤20; ≤3 params.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

from . import actors
from .actors import click_expression
from .chrome import ChromeMixin
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


class RdpClient(ChromeMixin):
    """A connection to one running Firefox's DevTools server.

    Tab operations live here; chrome-scope operations (the browser's own process, which
    is what switches its permission dialog off) come from `ChromeMixin` — RULE 16 keeps
    the class small, and the split is the real seam: same socket, different actor.
    """

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

    def connect(self, greeting_wait: float = GREETING_TIMEOUT) -> "RdpClient":
        """Open the socket and read the greeting (`greeting_wait` covers the Allow dialog)."""
        self._connection.connect(greeting_wait)
        return self

    @property
    def greeting(self) -> dict:
        """The root form ({} when this endpoint connected but never answered)."""
        return self._connection.greeting

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
        """One evaluation in a tab, through the shared per-actor machinery."""
        return self._eval_on(self._console_actor(tab, timeout), expression, timeout)

    def _console_actor(self, tab: actors.RdpTab, timeout) -> str:
        """The tab's console actor (cached per attach — actors die with the socket)."""
        cached = self._actor_cache.get(tab.id)
        return cached or self._resolve_console(tab, timeout)

    def _resolve_console(self, tab: actors.RdpTab, timeout) -> str:
        """The console actor behind one tab descriptor (`ctx-N` is the cache key)."""
        return self._resolve_actor(tab.actor, tab.id, timeout)


@contextmanager
def attach(point: Endpoint, timeout: float = DEFAULT_TIMEOUT):
    """A connected client for one operation, closed again whatever happens.

    Kept for a caller that really wants its own socket; the app's own paths use the
    shared session instead (round 11 — one socket per endpoint, or Firefox asks for
    permission once per operation).
    """
    client = RdpClient(point, timeout)
    client.connect()
    try:
        yield client
    finally:
        client.close()


def _shared(point: Endpoint):
    """The one session for this endpoint (imported lazily: `session` builds on this file)."""
    from .session import session_for
    return session_for(point)


def list_targets(point: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> Tuple[List[actors.RdpTab], str]:
    """Every tab of this Firefox, or ([] + why) — never raises.

    A parked endpoint answers its reason **without opening a socket**: that is what keeps
    the permission dialog from coming back on every pass.
    """
    session = _shared(point)
    if session.parked:
        return [], session.parked
    try:
        with session.use(timeout) as client:
            return client.tabs(timeout), ""
    except RdpError as e:
        return [], str(e)


def evaluate_json(point: Endpoint, tab_id: str, expression: str, timeout: float = DEFAULT_TIMEOUT):
    """Evaluate JS and return the parsed value, or (None + why)."""
    value, err, _kind = evaluate_typed(point, tab_id, expression, timeout)
    return value, err


def evaluate_typed(point: Endpoint, tab_id: str, expression: str, timeout: float = DEFAULT_TIMEOUT):
    """Evaluate JS and say what kind of failure it was: `(value, reason, kind)`.

    `kind` is `""` / `"js"` (the page threw) / `"timeout"` / `"transport"` — `attached`
    maps it onto its own `Answer`, so a page error is never reported as a dead socket.
    """
    session = _shared(point)
    if session.parked:
        return None, session.parked, "prompt"
    try:
        with session.use(timeout) as client:
            reply = client.evaluate(tab_id, expression, timeout)
            value, err = client.value_of(reply, timeout)
            return (None, err, "js") if err else (value, "", "")
    except RdpError as e:
        return None, str(e), ("timeout" if e.kind == "timeout" else "transport")


def click(point: Endpoint, tab_id: str, selector: str, timeout: float = DEFAULT_TIMEOUT):
    """Click one element (True + "" when it happened, else False + why)."""
    session = _shared(point)
    if session.parked:
        return False, session.parked
    try:
        with session.use(timeout) as client:
            return client.click(tab_id, selector, timeout)
    except RdpError as e:
        return False, str(e)


def session_info(point: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> Tuple[dict, str]:
    """Greeting + tab count of one DevTools server, or ({} + why)."""
    session = _shared(point)
    if session.parked:
        return {}, session.parked
    try:
        with session.use(timeout) as client:
            return client.info(), ""
    except RdpError as e:
        return {}, str(e)


def suppress_prompt(point: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> Tuple[bool, str]:
    """Tell the **running** Firefox to stop asking for permission (round 11, D-3)."""
    from . import prefs
    session = _shared(point)
    if session.parked:
        return False, session.parked
    try:
        with session.use(timeout) as client:
            return prefs.ask_to_stop(client, timeout)
    except RdpError as e:
        return False, str(e)
