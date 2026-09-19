"""Arena submit — prompt insert, verify, send (C3).

RULE18: file 150-300, func ≤20, CC≤10.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, Any, Tuple

from .js_snippets import JS_INSERT_PROMPT, JS_VERIFY_PROMPT, JS_CLICK_SEND, JS_SEND_STATE
from .highlight import highlight_selector


async def insert_prompt(cdp, prompt_text: str, ensure_connected) -> Tuple[bool, str]:
    if not await ensure_connected():
        return False, "Not connected"
    try:
        await highlight_selector(cdp, 'textarea[name="message"]', color="#00AAFF",
                                 duration_ms=1000, caption="Prompt")
    except Exception:
        pass
    js = f";({JS_INSERT_PROMPT})({json.dumps(prompt_text)})"
    result = await cdp.evaluate(js)
    if not result:
        return False, "No result"
    if result.get("ok"):
        return True, f"Inserted len {result.get('len')}"
    return False, result.get("error", "Unknown")


async def verify_prompt(cdp, expected: str) -> Tuple[bool, str]:
    js = f";({JS_VERIFY_PROMPT})({json.dumps(expected)})"
    result = await cdp.evaluate(js)
    if not result:
        return False, "No result"
    if result.get("ok"):
        return True, "Exact match"
    return False, f"Mismatch: {result}"


async def submit(cdp, ensure_connected) -> Tuple[bool, str]:
    if not await ensure_connected():
        return False, "Not connected"
    try:
        await highlight_selector(cdp, 'button[aria-label="Send message"]',
                                 color="#FFAA00", duration_ms=1000, caption="Send")
    except Exception:
        pass
    js = f";({JS_CLICK_SEND})()"
    result = await cdp.evaluate(js)
    if not result:
        return False, "No result"
    if result.get("ok"):
        return True, "Clicked"
    return False, result.get("error", "Failed")


async def _poll_send_state(cdp, timeout_sec: float) -> Dict[str, Any]:
    js = f";({JS_SEND_STATE})()"
    deadline = time.monotonic() + max(0.0, timeout_sec)
    state: Dict[str, Any] = {"found": False, "visible": False, "enabled": False}
    while True:
        res = await cdp.evaluate(js)
        if isinstance(res, dict):
            state = res
        if state.get("enabled") or time.monotonic() >= deadline:
            return state
        await asyncio.sleep(0.5)


async def submit_when_ready(cdp, ensure_connected, timeout_sec: float = 8.0) -> Tuple[bool, str]:
    if not await ensure_connected():
        return False, "Not connected"
    state = await _poll_send_state(cdp, timeout_sec)
    if not state.get("enabled"):
        if not state.get("found"):
            return False, "send not found"
        if not state.get("visible"):
            return False, "send hidden"
        return False, "send disabled"
    return await submit(cdp, ensure_connected)
