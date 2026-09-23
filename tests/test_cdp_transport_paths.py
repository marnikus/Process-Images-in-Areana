"""Error-path coverage for app/browser/cdp/transport.py.

RULE 8: no live Chrome — dead sockets and throwing tasks are faked so the
disconnect/receive-loop guards (swallow-and-continue) are pinned for real.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.cdp.transport import CDPTransport, _exception_text, _protocol_text

pytestmark = pytest.mark.unit


class DeadSocket:
    """An async-iterable websocket whose iterator dies immediately."""

    def __aiter__(self):
        raise RuntimeError("socket died")


async def _boom():
    raise RuntimeError("boom")


async def test_disconnect_swallows_task_and_close_errors():
    t = CDPTransport()
    task = asyncio.ensure_future(_boom())
    await asyncio.sleep(0)                     # let it finish with its exception
    t._receive_task = task
    t._ws = SimpleNamespace(close=_boom)       # close() raises too
    await t.disconnect()                       # must not raise
    assert t._ws is None and t._receive_task is None
    assert t._connected is False


async def test_receive_loop_reports_error_and_disconnected_guard():
    t = CDPTransport()
    t._connected = True
    t._current_ws_url = "ws://127.0.0.1:9222/devtools/page/x"
    t._ws = DeadSocket()
    errors = []
    t.error.connect(errors.append)
    t.disconnected = SimpleNamespace(emit=lambda: (_ for _ in ()).throw(RuntimeError("emit boom")))
    await t._receive_loop()
    assert len(errors) == 1 and "receive error" in errors[0]
    assert t._connected is False


def test_protocol_text_non_dict_and_exception_text_junk():
    assert _protocol_text("plain failure") == "plain failure"
    assert _exception_text(["junk"]) == "['junk']"
