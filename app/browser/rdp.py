"""Firefox DevTools RDP client — stealth attach to a running Firefox (2026-09-22).

Firefox's debugger server (`--start-debugger-server`, plain TCP `length:JSON`)
loads no Marionette and creates no WebDriver session, so `navigator.webdriver`
stays `false` — unlike `--remote-debugging-port` (BiDi), which taints the
browser by design. One pooled socket per endpoint: greeting → `listTabs` →
`getTarget` → `evaluateJSAsync` (ack + `evaluationResult` event) /
`navigateTo`, reused across ops (Firefox prompts once per CONNECTION, so a
fresh socket per op would re-prompt every fetch cycle). Actors die with the
connection, the browser and its real profile keep running, and attach/detach
needs no restart. A fresh connection also switches the approval prompt itself
off (`PreferenceActor.setBoolPref`, persisted by the server) — best-effort,
one log line when it flips, detection (`probe`) never touches it.

Sync on purpose: the CDP listing path (`cdp/tabs.fetch_tabs_sync`) is sync too
and runs in an executor, so both protocols look the same to their caller.

RULE 18: leaf module, funcs ≤20 LOC; every public helper degrades to a
(result, error-text) answer instead of raising, so a dead Firefox can never
break the pool or the reconciler loop.

# ideal-size: 400 lines reason=one leaf RDP client (framing + connection + pooled lifecycle + prompt flip share the packet helpers); splitting would scatter request/reply pairs.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

log = logging.getLogger("arena")

DEFAULT_TIMEOUT = 3.0
MAX_FRAME = 32 * 1024 * 1024


class Endpoint(NamedTuple):
    """One Firefox debugger server: host + port (every tab rides its socket)."""

    host: str
    port: int


class RdpError(RuntimeError):
    """A typed RDP failure: the actor's error code plus its message."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


def _read_bytes(fp, size: int) -> bytes:
    """Exactly `size` bytes, or an RdpError (timeout/close become transport)."""
    data = b""
    try:
        while len(data) < size:
            chunk = fp.read(size - len(data))
            if not chunk:
                raise RdpError("transport", "Firefox closed the connection")
            data += chunk
    except RdpError:
        raise
    except socket.timeout as e:
        raise RdpError("transport", "timed out waiting for Firefox") from e
    except OSError as e:
        raise RdpError("transport", f"connection lost: {e}") from e
    return data


def _read_prefix(fp) -> int:
    """The `length:` header of one frame (anything else is a protocol error)."""
    prefix = b""
    while True:
        digit = _read_bytes(fp, 1)
        if digit == b":":
            return int(prefix or b"0")
        prefix += digit
        if len(prefix) > 10 or digit not in b"0123456789":
            raise RdpError("protocol", f"bad RDP length prefix: {prefix!r:.32}")


def _recv_frame(fp) -> dict:
    """One `length:JSON` packet (bulk packets are never requested)."""
    size = _read_prefix(fp)
    if size > MAX_FRAME:
        raise RdpError("protocol", f"RDP frame too large: {size}")
    try:
        return json.loads(_read_bytes(fp, size).decode("utf-8"))
    except RdpError:
        raise
    except Exception as e:
        raise RdpError("protocol", f"non-JSON RDP frame: {e}") from e


def _send_frame(sock, payload: dict) -> None:
    """One frame out; a dead socket is a transport error (never raises else)."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    try:
        sock.sendall(str(len(raw)).encode() + b":" + raw)
    except OSError as e:
        raise RdpError("transport", f"connection lost: {e}") from e


def _wrap(expression: str) -> str:
    """One expression → a JSON-string answer (the CDP `returnByValue` shape)."""
    return ("(async()=>{const v=await(" + expression + ");"
            'try{return v===undefined?"null":JSON.stringify(v);}'
            'catch(e){return "null";}})()')


def _tab_key(entry: dict) -> str:
    """The stable tab id: `browserId`, else the context/window fallbacks."""
    for field in ("browserId", "browsingContextID", "outerWindowID", "actor"):
        value = entry.get(field)
        if value is not None and value != "":
            return str(value)
    return ""


def _row(entry: dict) -> dict:
    """A raw `listTabs` entry → an `{id, title, url}` row."""
    return {"id": _tab_key(entry), "title": str(entry.get("title", "") or ""),
            "url": str(entry.get("url", "") or "")}


def _exc_text(event: dict) -> str:
    """The page's own error text out of an `evaluationResult` exception."""
    if event.get("exceptionMessage"):
        return str(event["exceptionMessage"])
    preview = (event.get("exception") or {}).get("preview") or {}
    if isinstance(preview, dict) and preview.get("message"):
        return str(preview["message"])
    return "JS exception"


class RdpConnection:
    """One socket to the debugger server: greeting once, then requests."""

    def __init__(self, target: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.target = target
        self.timeout = timeout
        self._sock = None
        self._fp = None

    def connect(self) -> None:
        """Open the socket and read the greeting (no session is created)."""
        self.close()
        try:
            sock = socket.create_connection((self.target.host, int(self.target.port)),
                                            timeout=self.timeout)
            sock.settimeout(self.timeout)
        except OSError as e:
            raise RdpError("transport", f"Firefox not reachable: {e}") from e
        self._sock, self._fp = sock, sock.makefile("rb")
        try:
            greeting = self._recv()
        except RdpError:
            self.close()
            raise
        if greeting.get("from") != "root":
            self.close()
            raise RdpError("protocol", "not a Firefox debugger server")

    def close(self) -> None:
        """Close the socket; detaching never touches the browser."""
        fp, sock = self._fp, self._sock
        self._fp = self._sock = None
        for stream in (fp, sock):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    def _send(self, payload: dict) -> None:
        """One frame out (sending before `connect` is a transport error)."""
        if self._sock is None:
            raise RdpError("transport", "not connected")
        _send_frame(self._sock, payload)

    def _recv(self) -> dict:
        """One frame in, with the session timeout."""
        if self._fp is None:
            raise RdpError("transport", "not connected")
        return _recv_frame(self._fp)

    def request(self, to: str, rtype: str, extra: Dict[str, Any] = None) -> dict:
        """One request; unsolicited events are skipped, errors become RdpError."""
        self._send({"to": to, "type": rtype, **(extra or {})})
        while True:
            packet = self._recv()
            if packet.get("from") != to or "type" in packet:
                continue
            if packet.get("error"):
                raise RdpError(str(packet["error"]), str(packet.get("message", "")))
            return packet

    def list_tabs(self) -> List[dict]:
        """Raw `listTabs` entries (actors are valid for this connection only)."""
        reply = self.request("root", "listTabs")
        tabs = reply.get("tabs", [])
        return [t for t in tabs if isinstance(t, dict)]

    def resolve(self, tab_id: str) -> Tuple[str, str]:
        """(target actor, console actor) for a stable tab id, re-enumerated."""
        for entry in self.list_tabs():
            if _tab_key(entry) != tab_id:
                continue
            actor = str(entry.get("actor") or "")
            if not actor:
                raise RdpError("protocol", "listTabs entry without an actor")
            frame = self.request(actor, "getTarget").get("frame") or {}
            target, console = str(frame.get("actor", "")), str(frame.get("consoleActor", ""))
            if target and console:
                return target, console
            raise RdpError("protocol", f"no target for tab {tab_id!r}")
        raise RdpError("no-tab", f"no open tab {tab_id!r}")

    def evaluate(self, tab_id: str, expression: str) -> str:
        """Evaluate JS in one tab; the value comes back as a JSON string."""
        _target, console = self.resolve(tab_id)
        ack = self.request(console, "evaluateJSAsync",
                           {"text": _wrap(expression), "mapped": {"await": True}})
        return _unwrap_value(self, _await_eval(self, console, str(ack.get("resultID", ""))))

    def navigate(self, tab_id: str, url: str) -> str:
        """Navigate one tab; returns the URL the browser accepted."""
        target, _console = self.resolve(tab_id)
        self.request(target, "navigateTo", {"url": url})
        return url


def _await_eval(conn: RdpConnection, console: str, result_id: str) -> dict:
    """The `evaluationResult` event matching the ack (events are skipped)."""
    while True:
        packet = conn._recv()
        if packet.get("from") != console:
            continue
        kind = packet.get("type", "")
        if kind in ("tabNavigated", "willNavigate"):
            raise RdpError("navigated", "the tab navigated during the eval")
        if kind != "evaluationResult":
            continue
        if result_id and packet.get("resultID") not in ("", result_id):
            continue
        return packet


def _unwrap_value(conn: RdpConnection, event: dict) -> str:
    """An `evaluationResult` event → JSON-string value; exceptions raise."""
    if event.get("hasException") or event.get("exception"):
        raise RdpError("js", _exc_text(event))
    result = event.get("result")
    if isinstance(result, dict) and result.get("type") == "longString":
        return _deref_longstring(conn, result)
    if isinstance(result, str):
        return result
    if result is None or (isinstance(result, dict) and result.get("type") == "undefined"):
        return "null"
    return json.dumps(result)


def _deref_longstring(conn: RdpConnection, grip: dict) -> str:
    """A `longString` grip → its full text via `substring`."""
    actor, fallback = str(grip.get("actor") or ""), str(grip.get("initial", ""))
    try:
        length = int(grip.get("length", 0) or 0)
    except (TypeError, ValueError):
        return fallback
    if not actor or length <= 0:
        return fallback
    reply = conn.request(actor, "substring", {"start": 0, "end": length})
    return str(reply.get("substring", fallback))


def probe(target: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """True when a debugger server answers (greeting only — taints nothing)."""
    conn = RdpConnection(target, timeout)
    try:
        conn.connect()
        return True
    except RdpError:
        return False
    finally:
        conn.close()


_pool: Dict[Endpoint, Tuple[RdpConnection, "threading.Lock"]] = {}
_pool_guard = threading.Lock()
APPROVAL_WAIT = 10.0
PROMPT_PREF = "devtools.debugger.prompt-connection"


def reset_pool() -> None:
    """Close every pooled socket (tests + shutdown); the next op reconnects."""
    with _pool_guard:
        entries = list(_pool.values())
        _pool.clear()
    for conn, _lock in entries:
        conn.close()  # never raises (nulls first, closes guarded)


def _silence_prompt(conn: RdpConnection) -> None:
    """Best-effort: switch the per-connection approval prompt off (persists)."""
    try:
        tabs_reply = conn.request("root", "listTabs")
        pref = str(tabs_reply.get("preferenceActor") or "")
        if not pref:
            return
        current = conn.request(pref, "getBoolPref", {"value": PROMPT_PREF}).get("value")
        if current is False:
            return
        conn.request(pref, "setBoolPref", {"name": PROMPT_PREF, "value": False})
        log.info("Firefox connection prompt switched off (devtools.debugger.prompt-connection=false)")
    except Exception:
        return


def _connect_fresh(conn: RdpConnection) -> str:
    """Connect with the approval window ("" when live, prompt silenced)."""
    conn.timeout = APPROVAL_WAIT
    try:
        conn.connect()
    except RdpError as e:
        conn.close()
        return str(e)
    _silence_prompt(conn)
    return ""


def _revive(conn: RdpConnection, timeout: float) -> str:
    """Re-apply the caller timeout; a raced-close redials ("" when live)."""
    conn.timeout = timeout
    try:
        conn._sock.settimeout(timeout)
    except OSError:
        conn.close()
        return _connect_fresh(conn)
    return ""


def _run(target: Endpoint, timeout: float, action):
    """One pooled op: reuse the endpoint socket, reconnect when dead.

    Mutex-serialized; fresh conns wait the approval window; errors drop it.
    """
    with _pool_guard:
        entry = _pool.get(target)
        if entry is None:
            entry = (RdpConnection(target, timeout), threading.Lock())
            _pool[target] = entry
    conn, lock = entry
    with lock:
        if conn._sock is None:
            err = _connect_fresh(conn)
            if err:
                return None, err
        else:
            err = _revive(conn, timeout)
            if err:
                return None, err
        try:
            return action(conn), ""
        except RdpError as e:
            conn.close()
            return None, str(e)
        except Exception as e:
            conn.close()
            return None, f"{type(e).__name__}: {e}"


def list_tabs(target: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> Tuple[List[dict], str]:
    """The browser's tabs as `{id, title, url}` rows ([] + reason on failure)."""
    rows, err = _run(target, timeout, lambda c: [_row(e) for e in c.list_tabs() if _tab_key(e)])
    return (rows or [], err)


def evaluate(target: Endpoint, tab_id: str, expression: str,
             timeout: float = DEFAULT_TIMEOUT) -> Tuple[Optional[str], str]:
    """Evaluate JS in one tab (value-as-JSON, or None + reason)."""
    return _run(target, timeout, lambda c: c.evaluate(tab_id, expression))


def navigate(target: Endpoint, tab_id: str, url: str,
             timeout: float = DEFAULT_TIMEOUT) -> Tuple[bool, str]:
    """Navigate one tab (True + "" when the browser accepted it)."""
    url_out, err = _run(target, timeout, lambda c: c.navigate(tab_id, url))
    return (bool(url_out), err) if not err else (False, err)
