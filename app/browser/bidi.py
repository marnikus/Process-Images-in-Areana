"""WebDriver BiDi client — the protocol a current Firefox speaks (2026-09-21).

Firefox's Remote Agent serves the HTTP entry point and the session socket on ONE
port: `POST /session` answers `value.capabilities.webSocketUrl`, the socket then
requires `session.new` as its first command (BiDi spec), and the browser's tabs
are `browsingContext`s reached through that one session — not one socket per tab
like CDP. Commands implemented here are the ones the app needs to see and steer a
tab: `browsingContext.getTree` (the tab list), `script.evaluate` (the JS probes
the whole arena flow is built on) and `browsingContext.navigate`.

Sync on purpose: the CDP listing path (`cdp/tabs.fetch_tabs_sync`) is sync too
and runs in an executor, so both protocols look the same to their caller.

RULE 18: leaf module, funcs ≤20 LOC; every public helper degrades to a
(default, error-text) answer instead of raising, so a provider-less browser can
never break the pool or the reconciler loop.
"""

from __future__ import annotations

import json
import socket
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

SESSION_PATH = "/session"
DEFAULT_TIMEOUT = 3.0


class Endpoint(NamedTuple):
    """One browser's Remote Agent: host + port (every context rides its socket)."""

    host: str
    port: int


class BidiError(RuntimeError):
    """A typed BiDi failure: the agent's error code plus its message."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SessionRef:
    """What `POST /session` answers: the one socket every command rides."""

    ws_url: str
    session_id: str = ""


def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def _post_json(url: str, payload: dict, timeout: float) -> Optional[dict]:
    """POST JSON and parse the reply; None on any failure (never raises)."""
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _ws_url_of(reply: Any) -> Tuple[str, str]:
    """(ws url, session id) from a new-session reply, tolerating both shapes."""
    try:
        value = reply.get("value", reply) if isinstance(reply, dict) else {}
        caps = value.get("capabilities", {}) if isinstance(value, dict) else {}
        url = caps.get("webSocketUrl") or caps.get("webSocketDebuggerUrl") or ""
        return str(url or ""), str(value.get("sessionId", "") or "")
    except Exception:
        return "", ""


def _connect_ws(url: str, timeout: float):
    """Open the socket with the kwargs this websockets release understands.

    `legacy=True` (17.1+) keeps the eager connection and silences its
    context-manager deprecation; `proxy`/`legacy` are dropped on older releases
    (the repo allows websockets>=12).
    """
    from websockets.sync.client import connect as ws_connect
    kwargs = {"open_timeout": timeout, "max_size": 16 * 1024 * 1024,
              "proxy": None, "legacy": True}
    for unsupported in ((), ("legacy",), ("legacy", "proxy")):
        try:
            return ws_connect(url, **{k: v for k, v in kwargs.items() if k not in unsupported})
        except TypeError:
            continue
    raise BidiError("transport", "unsupported websockets client")


class BidiSession:
    """One socket to the browser: connect, `session.new` once, then commands."""

    def __init__(self, ref: SessionRef, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.ref = ref
        self.timeout = timeout
        self.session_new_sent = False
        self._ws = None
        self._cmd_id = 0

    @property
    def ws_url(self) -> str:
        """The session socket URL the browser handed out."""
        return self.ref.ws_url

    @property
    def session_id(self) -> str:
        """The session id the browser assigned ("" when it sent none)."""
        return self.ref.session_id

    def connect(self) -> None:
        """Open the socket (proxy off: this is a loopback endpoint)."""
        self._ws = _connect_ws(self.ref.ws_url, self.timeout)

    def close(self) -> None:
        """Close the socket; a broken socket is already closed."""
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None

    def _recv(self) -> dict:
        """One reply, with the session timeout (a closed socket is a transport error)."""
        try:
            raw = self._ws.recv(timeout=self.timeout)
        except Exception as e:
            raise BidiError("transport", str(e)) from e
        try:
            return json.loads(raw)
        except Exception as e:
            raise BidiError("protocol", f"non-JSON reply: {raw!r:.120}") from e

    def _send(self, method: str, params: Dict[str, Any]) -> dict:
        """Send one command and unwrap the reply (errors become BidiError)."""
        self._cmd_id += 1
        self._ws.send(json.dumps({"id": self._cmd_id, "method": method, "params": params or {}}))
        reply = self._recv()
        if reply.get("error"):
            raise BidiError(str(reply.get("error")), str(reply.get("message", "")))
        return reply.get("result", {}) or {}

    def ensure_session(self) -> None:
        """BiDi requires `session.new` as the first command; send it exactly once."""
        if self.session_new_sent:
            return
        self.session_new_sent = True
        try:
            self._send("session.new", {"capabilities": {}})
        except BidiError as e:
            if "session" not in str(e).lower():   # already-started agents are fine
                raise

    def command(self, method: str, params: Dict[str, Any] = None) -> dict:
        """Run one BiDi command on this session (`session.new` first, once)."""
        if self._ws is None:
            self.connect()
        self.ensure_session()
        return self._send(method, params or {})

    # ---- the three operations the app needs ----

    def get_tree(self) -> List[dict]:
        """Every browsing context the browser knows, flattened."""
        return _flatten(self.command("browsingContext.getTree", {}).get("contexts", []))

    def evaluate(self, context_id: str, expression: str) -> str:
        """Evaluate JS in one context; the value comes back as a JSON string."""
        result = self.command("script.evaluate", _eval_params(context_id, expression))
        return _unwrap_value(result)

    def navigate(self, context_id: str, url: str) -> str:
        """Navigate one context; returns the URL the browser reports."""
        result = self.command("browsingContext.navigate",
                              {"context": context_id, "url": url, "wait": "none"})
        return str(result.get("url", "") or "")


def _eval_params(context_id: str, expression: str) -> dict:
    """`script.evaluate` params, the way the spec wants them."""
    return {"expression": expression, "target": {"context": context_id},
            "awaitPromise": True, "resultOwnership": "none"}


def _unwrap_value(result: dict) -> str:
    """A `script.evaluate` result → JSON-string value; an exception → BidiError."""
    if str(result.get("type", "")) == "exception":
        detail = (result.get("exceptionDetails") or {}).get("text", "JS exception")
        raise BidiError("js", str(detail))
    return json.dumps((result.get("result") or {}).get("value"))


def _flatten(contexts: List[dict]) -> List[dict]:
    """The context tree as flat rows (`id`/`url`), parents before children."""
    rows: List[dict] = []
    for ctx in contexts or []:
        if not isinstance(ctx, dict):
            continue
        rows.append({"id": str(ctx.get("context", "") or ""),
                     "url": str(ctx.get("url", "") or ""),
                     "title": str(ctx.get("title", "") or "")})
        rows.extend(_flatten(ctx.get("children", [])))
    return [r for r in rows if r["id"]]


def open_session(target: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> Optional[BidiSession]:
    """Start a BiDi session on target; None when the endpoint does not speak it.

    The socket opens on the first command, so asking does not leak a connection.
    """
    host, port = target.host, target.port
    if not _port_open(host, port, min(timeout, 1.0)):
        return None
    body = {"capabilities": {"alwaysMatch": {}}}
    ws_url, session_id = _ws_url_of(_post_json(f"http://{host}:{port}{SESSION_PATH}", body, timeout))
    return BidiSession(SessionRef(ws_url, session_id), timeout) if ws_url else None


def _run(target: Endpoint, timeout: float, action):
    """Open → act → close; a failure is returned, never raised."""
    session = open_session(target, timeout)
    if session is None:
        return None, "no BiDi session"
    try:
        return action(session), ""
    except BidiError as e:
        return None, str(e)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        session.close()


def list_contexts(target: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> Tuple[List[dict], str]:
    """The browser's tabs as `{id, url, title}` rows ([] + reason on failure)."""
    rows, err = _run(target, timeout, lambda s: s.get_tree())
    return (rows or [], err)


def evaluate(target: Endpoint, context_id: str, expression: str,
             timeout: float = DEFAULT_TIMEOUT) -> Tuple[Optional[str], str]:
    """Evaluate JS in one context (value-as-JSON, or None + reason)."""
    return _run(target, timeout, lambda s: s.evaluate(context_id, expression))


def navigate(target: Endpoint, context_id: str, url: str,
             timeout: float = DEFAULT_TIMEOUT) -> Tuple[bool, str]:
    """Navigate one context (True + "" when the browser accepted it)."""
    url_out, err = _run(target, timeout, lambda s: s.navigate(context_id, url))
    return (bool(url_out), err) if not err else (False, err)
