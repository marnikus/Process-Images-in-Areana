"""A CDP socket that already closed never prints two tracebacks on Windows (I-75, owner paste 2026-09-27).

After `evaluate transport error: ConnectionError: CDP connection lost` the owner's console
showed `Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)` twice:
`OSError: [WinError 10038] … not a socket` from `self._sock.shutdown`, and websockets'
`StopIteration` from `receive_eof`. Python 3.10's Proactor loop cleaning up a socket that is
already gone — the transport had already handled the loss. Everything else is still reported.
"""
import asyncio

import pytest

from app.core import loop_noise as ln

pytestmark = pytest.mark.unit

HANDLE = "<Handle _ProactorBasePipeTransport._call_connection_lost(None)>"
MESSAGE = "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)"


def _not_a_socket():
    err = OSError(10038, "An operation was attempted on something that is not a socket")
    err.winerror = 10038
    return err


@pytest.mark.parametrize("exc", [_not_a_socket(), StopIteration()])
def test_the_two_teardown_callbacks_are_noise(exc):
    assert ln.is_socket_teardown_noise({"message": MESSAGE, "exception": exc, "handle": HANDLE})


@pytest.mark.parametrize("context", [
    {"message": MESSAGE, "exception": ValueError("real bug"), "handle": HANDLE},
    {"message": "Exception in callback other()", "exception": _not_a_socket(), "handle": "<Handle other()>"},
    {"message": MESSAGE, "exception": OSError(5, "access denied"), "handle": HANDLE},
    {"message": "Task was destroyed but it is pending!"},
])
def test_anything_else_is_not(context):
    assert not ln.is_socket_teardown_noise(context)


def test_noise_is_one_quiet_line_and_everything_else_reaches_the_previous_handler(caplog):
    loop = asyncio.new_event_loop()
    try:
        seen = []
        loop.set_exception_handler(lambda _lp, ctx: seen.append(ctx["message"]))
        assert ln.quiet_socket_teardown(loop) is loop
        with caplog.at_level("INFO", logger="arena"):
            loop.call_exception_handler({"message": MESSAGE, "exception": StopIteration(), "handle": HANDLE})
        loop.call_exception_handler({"message": "real", "exception": ValueError("x")})
        assert seen == ["real"]
        assert "socket teardown after a lost connection" in caplog.text
    finally:
        loop.close()


def test_without_a_previous_handler_the_default_one_reports(monkeypatch):
    loop = asyncio.new_event_loop()
    try:
        seen = []
        monkeypatch.setattr(loop, "default_exception_handler", lambda ctx: seen.append(ctx["message"]))
        ln.quiet_socket_teardown(loop)
        loop.call_exception_handler({"message": "real", "exception": ValueError("x")})
        assert seen == ["real"]
    finally:
        loop.close()
