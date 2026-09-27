"""Quiet the Windows socket-teardown callbacks that follow a lost CDP connection (I-75).

Owner paste 2026-09-27: after `evaluate transport error: ConnectionError: CDP
connection lost` — the transport had already failed its in-flight commands —
the console printed `Exception in callback
_ProactorBasePipeTransport._call_connection_lost(None)` twice:
`OSError: [WinError 10038] … not a socket` from `self._sock.shutdown`
(Python 3.10's Proactor loop cleaning up a socket that is already gone), and
websockets' `StopIteration` from `receive_eof` (the same end of stream seen a
second time). Those two, from that one callback, become one info line;
anything else still reaches the previous (or default) handler — a real error
is never hidden.

ideal-size: ~55 lines — one event-loop concern, installed once in main.py.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("arena")

_TEARDOWN_CALLBACK = "_call_connection_lost"
_NOT_A_SOCKET = 10038   # WSAENOTSOCK


def is_socket_teardown_noise(context: dict) -> bool:
    """The Proactor's own clean-up of an already-closed socket — nothing the app can act on."""
    where = f"{context.get('handle', '')} {context.get('message', '')}"
    if _TEARDOWN_CALLBACK not in where:
        return False
    exc = context.get("exception")
    if isinstance(exc, StopIteration):
        return True
    return isinstance(exc, OSError) and _NOT_A_SOCKET in (getattr(exc, "winerror", None), exc.errno)


def quiet_socket_teardown(loop: asyncio.AbstractEventLoop) -> asyncio.AbstractEventLoop:
    """Install the filter in front of the loop's handler; returns the loop (one line in main)."""
    previous = loop.get_exception_handler()

    def handler(lp: asyncio.AbstractEventLoop, context: dict) -> None:
        if is_socket_teardown_noise(context):
            log.info("socket teardown after a lost connection (Windows asyncio) — ignored: %r",
                     context.get("exception"))
        elif previous is not None:
            previous(lp, context)
        else:
            lp.default_exception_handler(context)

    loop.set_exception_handler(handler)
    return loop
