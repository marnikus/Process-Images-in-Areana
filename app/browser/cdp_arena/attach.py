"""Arena attach — image attach + verify (C3).

RULE18: file 150-300, func ≤20, CC≤10.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Tuple

from .js_snippets import JS_VERIFY_ATTACHMENT

log = logging.getLogger("arena")


async def verify_attachment(cdp, expected_filename: str) -> Tuple[bool, str]:
    js = f";({JS_VERIFY_ATTACHMENT})({json.dumps(expected_filename)})"
    result = await cdp.evaluate(js)
    if not result:
        return False, "No result"
    if result.get("found"):
        return True, f"Found via {result.get('matched')}"
    return False, f"Not found: {result}"


async def attach_image(cdp, image_path: str, ensure_connected, log_cb) -> Tuple[bool, str]:
    if not await ensure_connected():
        return False, "Not connected"
    ok, reason = await cdp.attach_image_cdp(image_path)
    if not ok:
        log_cb(f"Attach failed: {reason}", "warn")
        return False, reason
    log_cb(f"Attached {image_path}: {reason}")
    await asyncio.sleep(1)
    verified, vreason = await verify_attachment(cdp, Path(image_path).name)
    if verified:
        return True, vreason
    await asyncio.sleep(2)
    return await verify_attachment(cdp, Path(image_path).name)
