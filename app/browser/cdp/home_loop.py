"""One CDP socket, one event loop — whoever calls (I-76).

The app runs two asyncio loops: qasync's on the Qt thread and `arena-bg-loop`
(services/run_state). An asyncio socket belongs to the loop that opened it;
used from the other one, Qt refuses the foreign thread's callbacks ("QObject::
startTimer: Timers cannot be started from another thread", qasync `assert
timerid not in self.__callbacks`), a cancelled receive task never resumes
("Task was destroyed but it is pending!") and Windows' Proactor loses writes
("socket.send() raised exception" — Chrome never sees the command, 30 s
timeout, then a "silent socket" re-dial). Owner log 2026-09-27 22:37–22:58.

`@on_home_loop` goes on the few entry points that touch the socket (connect,
send, disconnect): the first caller's loop becomes the transport's home; a
call from any other loop is run there (`run_coroutine_threadsafe`) and its
result, exception or cancellation comes back. A home loop that stopped or
closed is replaced by the next caller's.

Public API: on_home_loop(coro_fn), running_loop().

ideal-size: ~55 lines — one invariant, shared by transport.py and connect.py.
"""
from __future__ import annotations

import asyncio
import functools
from typing import Optional


def running_loop() -> Optional[asyncio.AbstractEventLoop]:
    """The caller's running loop, or None outside one."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _hop_target(transport) -> Optional[asyncio.AbstractEventLoop]:
    """The live home loop when the caller is on another one; else claim the caller's loop."""
    home, here = getattr(transport, "_home_loop", None), running_loop()
    if home is not None and home is not here and home.is_running() and not home.is_closed():
        return home
    if home is None or not home.is_running() or home.is_closed():
        transport._home_loop = here
    return None


def on_home_loop(coro_fn):
    """Run `coro_fn(transport, …)` on the transport's home loop."""
    @functools.wraps(coro_fn)
    async def run(transport, *args, **kwargs):
        home = _hop_target(transport)
        if home is None:
            return await coro_fn(transport, *args, **kwargs)
        future = asyncio.run_coroutine_threadsafe(coro_fn(transport, *args, **kwargs), home)
        return await asyncio.wrap_future(future)
    return run
