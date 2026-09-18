"""CDP event fan-out kept separate from websocket transport.

Listeners receive raw `{method, params}` event messages. Async listeners are
scheduled, never awaited inside the receive loop, so they cannot deadlock by
sending another CDP command.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable

log = logging.getLogger("arena")
EventListener = Callable[[dict], Any]


class CDPEventRouter:
    """Small exception-isolated listener registry."""

    def __init__(self) -> None:
        self._listeners: set[EventListener] = set()

    def add(self, listener: EventListener) -> None:
        self._listeners.add(listener)

    def remove(self, listener: EventListener) -> None:
        self._listeners.discard(listener)

    def dispatch(self, message: dict) -> None:
        for listener in tuple(self._listeners):
            self._call(listener, message)

    @staticmethod
    def _call(listener: EventListener, message: dict) -> None:
        try:
            result = listener(message)
            if inspect.isawaitable(result):
                asyncio.create_task(result)
        except Exception as exc:
            log.warning("CDP event listener failed: %s", exc)


def route_cdp_message(client: Any, data: dict) -> None:
    """Resolve command replies or fan out unsolicited protocol events."""
    message_id = data.get("id")
    if message_id and message_id in client._pending:
        future = client._pending.pop(message_id)
        if not future.done():
            future.set_result(data)
        return
    if data.get("method"):
        client.events.dispatch(data)
