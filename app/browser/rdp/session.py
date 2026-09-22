"""One live DevTools socket per Firefox endpoint — the app's whole Firefox channel (round 11).

Round 10 reduced a listing pass to one connection *per browser*, which was still one
connection **per operation**: `rdp.attach()` is a context manager, so listing, every
evaluate and every click dialled again and closed. Measured on a real stub server, one
reconcile pass opened fifteen sockets (3 listings, 2 pool joins, 10 evaluates). Firefox
asks "An incoming request to permit remote debugging connection was detected" for **each
incoming connection** (`devtools/shared/security/auth.js` reads
`devtools.debugger.prompt-connection` per connection), so the owner's browser was asked
about fifteen times per pass, every pass — "never-ending permission request messages".

This module is the fix, in three parts:

* **one socket** (`Session.use`) shared by every operation, reused pass after pass, so a
  Firefox is asked at most once;
* **a wait instead of a race** — the first attach of an endpoint waits `ALLOW_WAIT` for
  the greeting (0.6 s was the old greeting timeout, far too short for a human to answer a
  dialog), which is why the log line is printed *before* the wait;
* **a park, never a loop** — a connection that connects but never greets is Firefox
  waiting on its dialog: the endpoint is parked with a named reason, automatic passes skip
  it without opening anything, and only an explicit user action (`retry_all`, wired to
  Reparse/Refresh/Diagnose) clears the park and asks again.

Once the first attach succeeds the running browser is asked to stop asking at all
(`prefs.ask_to_stop`, D-3). RULE 18: leaf module, no Qt, no UI imports.
"""

from __future__ import annotations

import logging
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Dict, List, Optional

from . import prefs
from .client import RdpClient
from .wire import DEFAULT_TIMEOUT, GREETING_TIMEOUT, Endpoint, RdpError, base_url

log = logging.getLogger(__name__)

ALLOW_WAIT = 25.0          # how long a FIRST attach waits for the "Allow" dialog
GREETING_WAIT = GREETING_TIMEOUT
PARKED_HINT = ("Press Reparse (or Refresh) to try once more, or run Prepare Profile and restart "
               "Firefox so it never asks again.")
NOT_DEVTOOLS = ("{url} answers HTTP instead of the DevTools socket — it is a browser started with "
                "the Remote Agent ({flag}), not --start-debugger-server. Listing it over its own "
                "protocol.")

_SESSIONS: Dict[str, "Session"] = {}
_LOCK = threading.Lock()
_NEWS: List[str] = []


def _key(point: Endpoint) -> str:
    return f"{point.host}:{int(point.port)}"


def waiting_line(point: Endpoint) -> str:
    """The line printed *before* the wait — a silent minute looks like a hang (D-2)."""
    return (f"⏳ Firefox at {base_url(point)} is asking to allow the DevTools connection — click "
            f"“Allow” in its dialog (waiting up to {ALLOW_WAIT:.0f} s)…")


def asking_reason(point: Endpoint) -> str:
    """Why a parked endpoint cannot be listed, and what the user can do about it."""
    return (f"Firefox at {base_url(point)} connected but did not answer — its “incoming request to "
            f"permit remote debugging connection” dialog is waiting for Allow. {PARKED_HINT}")


def http_identity(point: Endpoint, timeout: float = GREETING_WAIT) -> bool:
    """Does this endpoint answer HTTP? Then it is not the raw DevTools socket.

    A Firefox started with `--remote-debugging-port` (the Remote Agent) serves WebDriver
    BiDi/CDP over HTTP on the same port a DevTools socket would use, and it never showed a
    permission dialog. Without this question it would be parked for a dialog that does not
    exist, and its tabs would never be listed (round 7's BiDi path). One short request,
    asked once per endpoint — an HTTP answer needs no second attempt to believe.
    """
    try:
        urllib.request.urlopen(f"http://{point.host}:{int(point.port)}/", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True                    # a status line is an HTTP server, whatever it says
    except Exception:
        return False


class Session:
    """The one socket this app keeps to one Firefox DevTools server."""

    def __init__(self, point: Endpoint) -> None:
        self.point = point
        self.parked = ""
        self.http_like = False         # answered HTTP: this port is not the DevTools socket
        self._client: Optional[RdpClient] = None
        self._lock = threading.RLock()
        self._asked = False            # the long first wait has been spent for this endpoint
        self._suppress_tried = False

    # ── state ────────────────────────────────────────────────────────────

    def live(self) -> bool:
        """Is there a usable socket right now?"""
        return self._client is not None and not self.parked

    @contextmanager
    def use(self, timeout: Optional[float] = None):
        """Yield the shared client, serialising every exchange on the one socket."""
        with self._lock:
            yield self._take(timeout)

    def close(self) -> None:
        """Drop the socket (the browser is untouched)."""
        client, self._client = self._client, None
        if client is not None:
            client.close()

    def forget(self) -> None:
        """Drop the parked verdict *and* the socket — an explicit retry may ask once more."""
        self.parked = ""
        self.http_like = False
        self._asked = False
        self._suppress_tried = False
        self.close()

    def _park(self, reason: str) -> None:
        self.parked = reason
        self.close()

    # ── connecting ───────────────────────────────────────────────────────

    def _take(self, timeout: Optional[float]) -> RdpClient:
        if self.parked:
            raise RdpError(self.parked, "prompt")
        if self.http_like:
            raise RdpError(NOT_DEVTOOLS.format(url=base_url(self.point), flag="--remote-debugging-port"),
                           "protocol")
        if self._client is not None:
            return self._client
        wait = GREETING_WAIT if self._asked else ALLOW_WAIT
        self._asked = True
        if wait > GREETING_WAIT:
            log.info(waiting_line(self.point))
        client = RdpClient(self.point, timeout or DEFAULT_TIMEOUT)
        try:
            client.connect(greeting_wait=wait)
        except RdpError:
            raise                                   # connection refused/timeout: try again next pass
        if not client.greeting:
            client.close()
            if http_identity(self.point, GREETING_WAIT):
                self.http_like = True
                raise RdpError(NOT_DEVTOOLS.format(url=base_url(self.point),
                                                   flag="--remote-debugging-port"), "protocol")
            self._park(asking_reason(self.point))
            raise RdpError(self.parked, "prompt")
        self._client = client
        self._suppress()
        return client

    def _suppress(self) -> None:
        """Once per endpoint: tell the running browser to stop showing the dialog (D-3)."""
        if self._suppress_tried:
            return
        self._suppress_tried = True
        ok, reason = prefs.ask_to_stop(self._client, DEFAULT_TIMEOUT)
        _NEWS.append(f"🔓 {base_url(self.point)}: {reason}" if ok else
                     f"⚠ {base_url(self.point)}: {reason}")
        log.info("prompt suppression on %s: %s", base_url(self.point), reason)


def session_for(point: Endpoint) -> Session:
    """The one session for this endpoint, created on first use."""
    with _LOCK:
        found = _SESSIONS.get(_key(point))
        if found is None:
            found = _SESSIONS[_key(point)] = Session(point)
        return found


def parked_reason(point: Endpoint) -> str:
    """Why this endpoint is parked ('' when it is not). No socket is opened here."""
    with _LOCK:
        found = _SESSIONS.get(_key(point))
    return found.parked if found is not None else ""


def retry_all() -> None:
    """Explicit user action (Reparse / Refresh / Diagnose / Connect): allow one more ask."""
    with _LOCK:
        sessions = list(_SESSIONS.values())
    for session in sessions:
        session.forget()


def close_all() -> None:
    """Drop every socket and pending news (app shutdown, tests)."""
    with _LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
        _NEWS.clear()
    for session in sessions:
        session.close()


def drain_news() -> List[str]:
    """One-shot lines the panel prints (suppression outcome) — drained, never repeated."""
    with _LOCK:
        news, _NEWS[:] = list(_NEWS), []
    return news
