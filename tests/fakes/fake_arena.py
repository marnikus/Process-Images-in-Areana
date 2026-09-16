"""Fake Arena Controller — synthetic baseline + output, no real page (Phase 2).

RULE 18: file 150-300 LOC ideal, current ~130 LOC.
RULE 16: class LOC ≤150, methods ≤15.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class FakeArenaController:
    """Fake controller returning synthetic data."""

    def __init__(self, baseline_count: int = 2, new_src: str = "https://example.com/new.png"):
        self._baseline_count = baseline_count
        self._new_src = new_src
        self._attached: List[str] = []
        self._prompts: List[str] = []
        self._submitted = False

    async def capture_baseline(self) -> Dict[str, Any]:
        return {
            "output_count": self._baseline_count,
            "output_srcs": [f"https://example.com/old{i}.png" for i in range(self._baseline_count)],
            "outputs": [],
            "timestamp": 1000,
        }

    async def attach_image(self, image_path: str):
        self._attached.append(image_path)
        return True, f"Attached {image_path}"

    async def verify_attachment(self, expected_filename: str):
        return True, f"Found {expected_filename}"

    async def insert_prompt(self, prompt_text: str):
        self._prompts.append(prompt_text)
        return True, f"Inserted len {len(prompt_text)}"

    async def verify_prompt(self, expected: str):
        if self._prompts and self._prompts[-1] == expected:
            return True, "Exact match"
        return False, "Mismatch"

    async def submit(self):
        self._submitted = True
        return True, "Clicked"

    async def wait_for_new_output(self, baseline, timeout_ms=180000, correlation_id=None, cancel_check=None):
        # Return synthetic new output with matching JOB-ID
        return "completed", {
            "new_src": self._new_src,
            "check": {"ready": True, "src": self._new_src, "associatedJobId": correlation_id, "expectedJobId": correlation_id},
            "baseline": baseline,
            "rect": {"x": 0, "y": 0, "width": 100, "height": 100},
        }

    async def download_image(self, src: str):
        return True, b"\x89PNG\r\n\x1a\nfake", "image/png"

    def get_attached(self) -> List[str]:
        return list(self._attached)

    def get_prompts(self) -> List[str]:
        return list(self._prompts)

    def was_submitted(self) -> bool:
        return self._submitted
