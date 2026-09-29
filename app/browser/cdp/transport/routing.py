from __future__ import annotations
import json
import logging
import time
from ...cdp_events import route_cdp_message
from ..liveness import note_late_reply

log = logging.getLogger("arena")

def _route(transport, raw, data: dict) -> None:
    size, kind = len(raw), str(data.get("method") or "reply")
    transport.last_rx = {"at": time.monotonic(), "bytes": size, "kind": kind}
    if size > getattr(transport, "largest_rx", {}).get("bytes", 0):
        transport.largest_rx = {"bytes": size, "kind": kind}
    note_late_reply(transport, data.get("id"))
    route_cdp_message(transport, data)

async def _send_payload(transport, cmd_id: int, ws, payload: str) -> None:
    try:
        await ws.send(payload)
    except Exception:
        transport._pending.pop(cmd_id, None)
        raise
