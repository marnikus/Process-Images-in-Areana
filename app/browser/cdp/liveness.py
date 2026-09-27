"""A socket that went silent — tell it from a page that is not answering, and re-dial (I-72).

Owner log 2026-09-27 18:05: right after Submit, both connections to the tab
(the job's and the Watcher's) stopped answering — even
`Page.getNavigationHistory`, which Chrome answers in the browser process
while the page's own scripts are stuck. So the page was not the only
suspect: the socket could be the silent part. Measured in Chrome: with the
Network domain on, one large page WebSocket frame (60 MB) kills our socket
with 1009 — the app no longer enables Network (`connect.CDP_DOMAINS`); this
module covers every other way a socket can go quiet.

When the 3 s ping on the job's socket fails, a throw-away socket to the SAME
tab pings once: it answers → our socket is wedged → re-dial in place (same
client object, the job keeps it); it is silent too → the page / Chrome is not
answering, and the wait's reason says so.

I-73 (owner log 22:38, a verified image 75 s after Submit): a socket that heard
Chrome seconds ago is alive — the PAGE is busy, never re-dialled; a reply to a
command we stopped waiting for is told with its delay (`⌛ Chrome answered …
34 s after it was sent`) — the measured busy time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

log = logging.getLogger("arena")

FRESH_PING_S = 3.0
SECOND_PING_S = 1.5
RECENT_RX_S = 5.0
REDIAL_TIMEOUT_S = 15.0
LATE_BOOK_MAX = 32
LATE_TELL_EVERY_S = 20.0
_PING = json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": "1", "returnByValue": True}})


async def fresh_socket_answers(url: str, timeout_s: Optional[float] = None) -> bool:
    """Dial a throw-away socket to the tab and ping once (does the page answer at all?)."""
    try:
        return await asyncio.wait_for(_ping_once(url), timeout=timeout_s or FRESH_PING_S)
    except Exception:
        return False


async def _ping_once(url: str) -> bool:
    """One socket, one ping, read until its reply (events may come first)."""
    import websockets
    async with websockets.connect(url, max_size=None, ping_interval=None,
                                  open_timeout=FRESH_PING_S, close_timeout=1) as ws:
        await ws.send(_PING)
        while True:
            if json.loads(await ws.recv()).get("id") == 1:
                return True


async def revive_silent_socket(cdp) -> bool:
    """Our socket is silent but a fresh one answers: re-dial the same tab in place.

    I-73 (owner log 22:38): a socket that heard Chrome seconds ago is alive —
    the PAGE is busy; and when a fresh socket answers, ours gets one more ping
    first (the page just came back, our queued replies flow again). Only a
    socket that stays silent while the tab answers others is re-dialled.
    """
    url = str(getattr(cdp, "_current_ws_url", "") or "")
    if not url or not callable(getattr(cdp, "connect", None)):
        return False
    if heard_recently(cdp):
        _note(cdp, _BUSY_PAGE)
        return False
    if not await fresh_socket_answers(url):
        _note(cdp, _SILENT_TAB)
        return False
    return await _answers_again(cdp) or await _redial_reported(cdp, url)


async def _answers_again(cdp) -> bool:
    """The tab answers a fresh socket: does ours answer now too (busy page, not a wedge)?"""
    from ..page_recovery import page_answers
    return await page_answers(cdp, SECOND_PING_S)


async def _redial_reported(cdp, url: str) -> bool:
    """Re-dial with the before/after lines."""
    _tell(cdp, f"🔌 CDP socket went silent ({rx_text(cdp)}) while the tab still answers — re-dialling it")
    ok = await _redial(cdp, url)
    _tell(cdp, "🔌 CDP socket re-dialled — continuing" if ok else "🔌 CDP re-dial failed")
    if ok:
        cdp.last_error, cdp.last_error_kind = "", ""
    return ok


_SILENT_TAB = "a fresh socket to the tab got no answer either"
_BUSY_PAGE = "the socket is alive — the page itself is busy"


def _note(cdp, words: str) -> None:
    """Say once, in the evaluate record, what the silence is (tab silent / page busy)."""
    if words not in str(cdp.last_error):
        cdp.last_error = f"{cdp.last_error}; {words}"[:300]


def heard_recently(cdp) -> bool:
    """Chrome sent our socket something within RECENT_RX_S — the socket is not the silent part."""
    last = getattr(cdp, "last_rx", None) or {}
    return bool(last) and time.monotonic() - float(last.get("at", 0.0)) <= RECENT_RX_S


def note_timed_out(transport, cmd_id: int, method: str, timeout: float) -> None:
    """Remember a command we stopped waiting for; its late reply measures how busy the page was."""
    book = transport.__dict__.setdefault("timed_out", {})
    book[cmd_id] = (method, time.monotonic() - float(timeout))
    while len(book) > LATE_BOOK_MAX:
        book.pop(next(iter(book)))


def note_late_reply(transport, msg_id) -> None:
    """A reply for a timed-out command: tell how late it came (throttled per socket)."""
    entry = (getattr(transport, "timed_out", None) or {}).pop(msg_id, None)
    if entry is None:
        return
    late = time.monotonic() - entry[1]
    transport.last_late_s = late
    if time.monotonic() - getattr(transport, "_late_told_at", -LATE_TELL_EVERY_S) >= LATE_TELL_EVERY_S:
        transport._late_told_at = time.monotonic()
        _tell(transport, f"⌛ Chrome answered {entry[0]} {late:.0f} s after it was sent — the page was "
                         f"busy that long (the app's checks take well under a second)")


async def _redial(cdp, url: str) -> bool:
    """Drop the wedged socket (bounded — its close may hang too), then connect again."""
    try:
        await asyncio.wait_for(cdp.disconnect(), timeout=REDIAL_TIMEOUT_S)
    except Exception as exc:
        log.warning("silent socket disconnect: %s", exc)
    try:
        return bool(await asyncio.wait_for(cdp.connect(url), timeout=REDIAL_TIMEOUT_S))
    except Exception as exc:
        log.warning("silent socket re-dial: %s", exc)
        return False


def rx_text(cdp) -> str:
    """'last message 34 s ago: Network.dataReceived 0.2 KB; largest 41.3 MB Network.webSocketFrameReceived'."""
    last = getattr(cdp, "last_rx", None) or {}
    if not last:
        return "nothing received yet"
    ago = time.monotonic() - float(last.get("at", time.monotonic()))
    text = f"last message {ago:.0f} s ago: {last.get('kind', '?')} {_size(last.get('bytes', 0))}"
    big = getattr(cdp, "largest_rx", None) or {}
    return text + (f"; largest {_size(big['bytes'])} {big.get('kind', '?')}" if big else "")


def _size(n) -> str:
    """Bytes in words (KB below a megabyte, MB above)."""
    n = float(n or 0)
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.1f} KB"


def _tell(cdp, note: str) -> None:
    """One warn line through the client's UI reporter (set by `dialogs.report_to_log`)."""
    watch = getattr(cdp, "dialogs", None)
    report = getattr(watch, "report", None) or log.warning
    try:
        report(note)
    except Exception:
        log.warning(note)
