"""Arena state — readiness, security, generation (C3).

RULE18: file 150-300, func ≤20, CC≤10.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, List, Tuple, Optional

from ..output_probes import build_baseline_js
from ..output_probes import build_check_js
from .js_snippets import JS_PAGE_READY, JS_SECURITY_DIALOG, JS_IS_GENERATING
from ...utils.page_errors import build_error_scan_js

log = logging.getLogger("arena")


async def capture_baseline(cdp) -> Dict[str, Any]:
    import time
    js = build_baseline_js()
    result = await cdp.evaluate(js)
    if not result:
        return {"output_count": 0, "output_srcs": [], "timestamp": int(time.time() * 1000)}
    return result


async def scan_page_errors(cdp) -> str:
    try:
        res = await cdp.evaluate(build_error_scan_js())
        return res if isinstance(res, str) else ""
    except Exception:
        return ""


async def is_page_ready(cdp) -> Tuple[bool, List[str]]:
    result = await cdp.evaluate(JS_PAGE_READY)
    if not result:
        return False, ["No result"]
    return bool(result.get("ready")), result.get("reasons", [])


async def is_security_dialog_visible(cdp) -> bool:
    result = await cdp.evaluate(JS_SECURITY_DIALOG)
    return bool(result)


async def is_generating(cdp) -> Tuple[bool, Dict[str, Any]]:
    try:
        result = await cdp.evaluate(JS_IS_GENERATING)
        if not result:
            return False, {}
        is_gen = bool(result.get("isGenerating") or result.get("spinning"))
        return is_gen, result
    except Exception as e:
        log.debug(f"is_generating failed {e}")
        return False, {"error": str(e)}


async def get_generation_state(cdp, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    js = build_check_js([], correlation_id, [])
    try:
        result = await cdp.evaluate(js)
        return result or {}
    except Exception as e:
        return {"error": str(e), "spinning": False}


async def reload_page(cdp, log_cb) -> Tuple[bool, str]:
    try:
        log_cb("🔄 Reloading page after timeout", "warn")
        try:
            await cdp.send("Page.reload", {}, timeout=15)
        except Exception as e:
            log_cb(f"Page.reload failed {e}, trying location.reload", "warn")
            try:
                await cdp.evaluate("window.location.reload(); true")
            except Exception as e2:
                return False, f"Both reload failed: {e} / {e2}"
        await asyncio.sleep(4)
        for i in range(10):
            ready, _ = await is_page_ready(cdp)
            if ready:
                log_cb(f"✅ Reloaded ready after {i+1}s", "success")
                return True, "Reloaded and ready"
            await asyncio.sleep(1)
        log_cb("⚠ Reloaded but not fully ready", "warn")
        return True, "Reloaded not fully ready"
    except Exception as e:
        log_cb(f"Reload failed {e}", "error")
        return False, str(e)
