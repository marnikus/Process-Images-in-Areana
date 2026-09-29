from __future__ import annotations
from typing import Any

async def _connect_all(clients: list, ws_url: str) -> bool:
    results = [await client.connect(ws_url) for client in clients]
    return all(results)

def _quietly(step: Any) -> None:
    try:
        if step is not None:
            step()
    except Exception:
        pass

def _log(move, message: str, level: str) -> None:
    try:
        move.ctx.bridge._log(message, level)
    except Exception:
        pass
