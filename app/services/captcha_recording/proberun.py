"""Page agents for one recording and the small runner that invokes them.

The agents are real files (RULE 8: the node harness executes these exact
strings); the runner only performs the CDP round trip and normalizes what came
back, so a probe failure is a soft, counted condition and never an exception
inside the recorder loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_JS = Path(__file__).parent / "recording_js"


def _read(name: str) -> str:
    return (_JS / name).read_text(encoding="utf-8").strip()


def install_probe() -> str:
    return _read("install.js")


def drain_probe() -> str:
    return _read("drain.js")


def snapshot_probe() -> str:
    return _read("snapshot.js")


def stop_probe() -> str:
    return _read("stop.js")


class ProbeRunner:
    """Install/drain/snapshot/stop the page agents through one CDP evaluate path."""

    def __init__(self, cdp: Any):
        self.cdp = cdp
        self.calls = {"drain": 0, "snapshot": 0, "error": 0}

    async def install(self) -> bool:
        return bool(self._as_dict(await self._evaluate(install_probe())).get("ok"))

    async def drain(self) -> dict[str, Any]:
        self.calls["drain"] += 1
        return self._as_dict(await self._evaluate(drain_probe()))

    async def snapshot(self) -> dict[str, Any]:
        self.calls["snapshot"] += 1
        return self._as_dict(await self._evaluate(snapshot_probe()))

    async def stop(self) -> None:
        await self._evaluate(stop_probe())

    async def _evaluate(self, script: str) -> Any:
        try:
            return await self.cdp.evaluate(script)
        except Exception:
            self.calls["error"] += 1
            return {}

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            data = json.loads(value) if isinstance(value, str) else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
