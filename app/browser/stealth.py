"""Is this browser session flagged? Ask the page (round 10).

The owner's report was about the robot icon in the URL bar, and the honest answer has two halves:
that icon is Firefox's own chrome, invisible to websites — and what websites *can* read is
`navigator.webdriver`, which belongs to Marionette / the Remote Agent, not to the DevTools socket
this app uses. Round 8 *said* that; this module *measures* it, in the tab that is attached, and the
panel prints the answer, so the claim can be checked on the owner's own machine.

One expression, one parse, one verdict — no other module writes its own stealth probe.

RULE 18: leaf module, ≤3 params, ≤20 LOC per function.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

STEALTH_JS = ("JSON.stringify({webdriver: !!navigator.webdriver, ua: navigator.userAgent, "
              "plugins: ((navigator.plugins && navigator.plugins.length) || 0), "
              "languages: navigator.language || '', "
              "headless: /headless/i.test(navigator.userAgent)})")


def measure(handle, tab_id: str, timeout: float = 5.0) -> Tuple[Dict[str, Any], str]:
    """`(facts, reason)` from one evaluation in that tab — any channel, never raises."""
    from . import attached
    target = attached.Handle(handle.ws_url, handle.channel, handle.host, handle.port, tab_id,
                             handle.browser)
    answer = attached.evaluate(target, STEALTH_JS, timeout)
    if answer.error:
        return {}, answer.error
    return parse(answer.value)


def parse(raw) -> Tuple[Dict[str, Any], str]:
    """The page's answer as a dict, or ({} + why) when it is not the JSON object we asked for."""
    if isinstance(raw, dict):
        return raw, ""
    if not raw:
        return {}, "the tab answered nothing to the stealth probe"
    try:
        facts = json.loads(raw)
    except (TypeError, ValueError):
        return {}, f"the stealth probe answered something else: {str(raw)[:80]}"
    return (facts, "") if isinstance(facts, dict) else ({}, "the stealth probe answered no object")


def verdict(facts: Optional[Dict[str, Any]]) -> str:
    """What is wrong with this session ("" when nothing is) — named, never smoothed over."""
    facts = facts or {}
    if facts.get("webdriver"):
        return ("navigator.webdriver=true — this browser IS flagged as automated (Marionette / "
                "Remote Agent). Restart Firefox with --start-debugger-server, never with "
                "--remote-debugging-port (Firefox bug 1719505).")
    if facts.get("headless"):
        return "the user agent says headless — start the normal window, not a headless one"
    return ""


def line(facts: Optional[Dict[str, Any]]) -> str:
    """The one log line: the measured state, and the verdict when there is one."""
    facts = facts or {}
    state = (f"🔎 Stealth check on this page: navigator.webdriver="
             f"{str(bool(facts.get('webdriver'))).lower()} · "
             f"{int(facts.get('plugins') or 0)} plugin(s) reported · "
             f"{(facts.get('languages') or '')} · "
             f"UA {str(facts.get('ua') or '')[:70]}")
    problem = verdict(facts)
    return f"{state}\n⚠ {problem}" if problem else f"{state} — a normal session as far as the page can tell"
