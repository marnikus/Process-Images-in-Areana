"""Open a tab *through* the job tab: the page can only reach its own profile (I-79 v5).

`Target.createTarget` refuses regular-profile contexts (design §4), so the fallback opener is the
job tab's own page calling `window.open`. The payload is built as a JSON text — quotes, newlines
and backslashes survive any URL (RULE 21-safe: same pattern as the other JS builders).

RULE 18: file ~60, func 4-20 LOC. Imports: stdlib only (a leaf module).
"""
from __future__ import annotations

import json
from typing import Any

_OPEN_JS = """
(() => {
  const url = __URL__;
  try {
    const opened = window.open(url, '_blank');
    return {ok: !!opened, error: opened ? '' : 'window.open returned null (popup blocked)'};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
})()
"""


def build_open_tab_js(url: str) -> str:
    """`window.open(url, '_blank')` in the page, reporting whether the popup was allowed."""
    return _OPEN_JS.replace("__URL__", json.dumps(str(url or "")))


def _error_of(reply: dict) -> str:
    error = reply.get("error")
    if not error:
        return ""
    return str(error.get("message") if isinstance(error, dict) else error)


def _value_of(reply: dict) -> Any:
    """`Runtime.evaluate` answers `result.result.value`; accept the flat shape too (fakes)."""
    payload = reply.get("result")
    if not isinstance(payload, dict):
        return None
    inner = payload.get("result")
    value = inner.get("value") if isinstance(inner, dict) else payload.get("value")
    return value


def _verdict(reply: dict) -> tuple[bool, str]:
    error = _error_of(reply)
    if error:
        return False, error
    value = _value_of(reply)
    if not isinstance(value, dict):
        return False, "the page did not confirm the open"
    if value.get("ok"):
        return True, ""
    return False, str(value.get("error") or "the page refused to open a tab")


async def open_tab_via_page(client, url: str, timeout_sec: float = 5.0) -> tuple[bool, str]:
    """Run the opener in the job tab; `(True, "")` only when the page reports a real new tab.

    `userGesture` makes the call a gesture, so Chrome's popup blocker treats the tab as
    user-requested instead of blocking it (a blocked popup must surface as a reason, R3).
    """
    params = {"expression": build_open_tab_js(url), "returnByValue": True,
              "awaitPromise": True, "userGesture": True}
    try:
        reply = await client.send("Runtime.evaluate", params, timeout=timeout_sec)
    except Exception as exc:
        return False, str(exc)
    if not isinstance(reply, dict):
        return False, "no answer from the page"
    return _verdict(reply)
