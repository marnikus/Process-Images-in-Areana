"""Fake Action Runner — returns OK/FAIL per step, no CDP (Phase 2).

RULE 18: file 150-300 LOC ideal, current ~100 LOC.
"""

from __future__ import annotations

from typing import Dict, List


class FakeActionRunner:
    """Fake runner that returns canned results per block."""

    def __init__(self, results: Dict[str, str] | None = None):
        # results: block_id -> "ok" | "fail" | "needs_review"
        self._results = results or {}
        self._executed: List[str] = []

    async def run_block(self, block_id: str, **kwargs) -> Dict:
        self._executed.append(block_id)
        result = self._results.get(block_id, "ok")
        if result == "ok":
            return {"ok": True, "block_id": block_id}
        if result == "needs_review":
            return {"ok": False, "needs_review": True, "block_id": block_id, "error": "needs review"}
        return {"ok": False, "block_id": block_id, "error": f"{block_id} failed"}

    def get_executed(self) -> List[str]:
        return list(self._executed)

    def set_result(self, block_id: str, result: str):
        self._results[block_id] = result
