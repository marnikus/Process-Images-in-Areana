"""RDP actors — the pure packet shapes, and the click-only expression.

Firefox's actor model in one line: the **tab** is a `browsingContextID` (stable,
survives reconnects), while the actors that hang off it (`tabDescriptorN` →
`targetN` → `consoleActorN`) are per connection and die with it. Everything in
this module is a pure function over a decoded packet, so the shapes a real
Firefox sends across versions can be pinned by tests without a socket.

Shapes pinned here (from the protocol docs and live transcripts, design §2):
* `listTabs` → `{"from":"root","tabs":[<descriptor>, …]}`,
* `getTarget` → `{"from":<descriptor>,"form":{…,"consoleActor":…}}` (a flat form
  is tolerated: older/other actors answer without the `form` wrapper),
* a dead actor → `{"from":<actor>,"error":"noSuchActor"}`,
* `evaluateJSAsync` → `{"resultID":…}` plus an `evaluationResult` event,
* a big value → a `longString` grip (`initial` + `length`) fetched with
  `substring`.

RULE 18: file ≤300, func ≤30, CC ≤10, ≤3 params.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .wire import PROTOCOL, RdpError

EVENT_TYPES = frozenset({"evaluationResult"})
CONSOLE_ACTORS_MARK = "consoleActor"   # actor ids that only ever push events


@dataclass(frozen=True)
class RdpTab:
    """One Firefox tab: identity = the browsing context, actors = this connection."""

    id: str
    title: str
    url: str
    actor: str = ""
    browser_id: int = 0
    outer_window_id: int = 0
    is_zombie: bool = False
    selected: bool = False
    traits: Dict[str, Any] = field(default_factory=dict)
    protocol: str = PROTOCOL
    ws_url: str = ""      # the app's handle for this tab (`rdp://host:port/ctx-N`)


def tab_id(browsing_context_id) -> str:
    """The stable handle of a tab (`ctx-<n>`) — the thing that survives reconnects."""
    try:
        return f"ctx-{int(browsing_context_id)}"
    except Exception:
        return f"ctx-{browsing_context_id}"


def text_field(descriptor: dict, name: str) -> str:
    """A string field of a descriptor/reply ("" when absent)."""
    return str((descriptor or {}).get(name) or "")


def int_field(descriptor: dict, name: str) -> int:
    """An integer field of a descriptor/reply (0 when absent or unusable)."""
    try:
        return int((descriptor or {}).get(name) or 0)
    except Exception:
        return 0


def tab_of_descriptor(descriptor: dict) -> Optional[RdpTab]:
    """One descriptor row as a tab; None when it cannot be a tab at all."""
    if not isinstance(descriptor, dict):
        return None
    actor = text_field(descriptor, "actor")
    context = descriptor.get("browsingContextID")
    if context is None and not actor:
        return None
    return RdpTab(
        id=tab_id(context if context is not None else actor),
        title=text_field(descriptor, "title"), url=text_field(descriptor, "url"), actor=actor,
        browser_id=int_field(descriptor, "browserId"),
        outer_window_id=int_field(descriptor, "outerWindowID"),
        is_zombie=bool(descriptor.get("isZombieTab")), selected=bool(descriptor.get("selected")),
        traits=dict(descriptor.get("traits") or {}),
    )


def tabs_in(packet: dict) -> List[RdpTab]:
    """Every tab of a `listTabs` reply (unknown shapes are skipped, never guessed)."""
    if not isinstance(packet, dict):
        return []
    tabs = packet.get("tabs")
    if not isinstance(tabs, list):
        return []
    return [t for t in (tab_of_descriptor(d) for d in tabs) if t is not None]


def target_form(packet: dict) -> Dict[str, Any]:
    """The target/tab form of a `getTarget` (or `attach`) reply, wrapper or flat."""
    if not isinstance(packet, dict):
        return {}
    form = packet.get("form")
    return form if isinstance(form, dict) else packet


def console_actor_of(form: dict) -> str:
    """The console (evaluation) actor of a target form — "" when it hides it."""
    return str((form or {}).get("consoleActor") or "")


def parent_process(packet: dict) -> str:
    """The parent (browser) process descriptor of a `listProcesses` reply — "" when absent.

    Only Firefox started with `--start-debugger-server` answers this: the flag sets
    `DevToolsServer.allowChromeProcess`, and the descriptor it returns carries
    `isParent`. Older builds list content processes only, in which case there is no
    chrome scope to evaluate in and the caller degrades by name.
    """
    rows = packet.get("processes") if isinstance(packet, dict) else None
    if not isinstance(rows, list):
        return ""
    forms = [r for r in rows if isinstance(r, dict) and r.get("actor")]
    for row in forms:
        if row.get("isParent") or row.get("isParentProcess"):
            return str(row["actor"])
    return str(forms[0]["actor"]) if forms else ""


def actor_types(packet: dict) -> Set[str]:
    """The command names an actor announced for `requestTypes`."""
    if not isinstance(packet, dict):
        return set()
    names = packet.get("types")
    if not isinstance(names, list):
        names = packet.get("requestTypes")
    return {str(n) for n in names} if isinstance(names, list) else set()


def result_id(packet: dict) -> str:
    """The id of an asynchronous evaluation (`evaluateJSAsync`)."""
    return str((packet or {}).get("resultID") or "")


def result_matches(packet: dict, wanted: str) -> bool:
    """Is this `evaluationResult` event the answer to that result id?"""
    if not wanted or not isinstance(packet, dict):
        return False
    return str(packet.get("type") or "") in EVENT_TYPES and result_id(packet) == wanted


def result_grip(packet: dict) -> Dict[str, Any]:
    """The value grip of an evaluation reply (`{}` when there is none)."""
    grip = (packet or {}).get("result")
    return grip if isinstance(grip, dict) else {}


def exception_text(packet: dict) -> str:
    """The JS error text of an evaluation reply — "" when it threw nothing."""
    if not isinstance(packet, dict):
        return ""
    if not (packet.get("exception") or packet.get("exceptionMessage")):
        return ""
    return str(packet.get("exceptionMessage") or "JS exception")


def string_value(packet: dict) -> Optional[str]:
    """The plain string value of an evaluation reply (None for other grips)."""
    grip = result_grip(packet)
    value = grip.get("value")
    return value if grip.get("type") == "string" and isinstance(value, str) else None


def is_long_string(packet: dict) -> bool:
    """True when the value came back as a `longString` grip (needs `substring`)."""
    return result_grip(packet).get("type") == "longString"


def initial_text(packet: dict) -> str:
    """The truncated head of a long string."""
    return str(result_grip(packet).get("initial") or "")


def total_length(packet: dict) -> int:
    """The full length of a long string (0 when it does not say)."""
    try:
        return int(result_grip(packet).get("length") or 0)
    except Exception:
        return 0


def substring_text(packet: dict) -> str:
    """The chunk a `substring` reply carries."""
    return str((packet or {}).get("substring") or "")


def is_event(packet: dict) -> bool:
    """An unsolicited push: it comes from a console actor AND carries a type.

    Both halves matter. `tabAttached` is also typed but answers `attach`, and a
    console reply carries no `type` — one rule, no special cases at call sites.
    """
    if str(packet.get("type") or "") in EVENT_TYPES:
        return True
    return bool(packet.get("type")) and CONSOLE_ACTORS_MARK in str(packet.get("from") or "")


def packet_error(packet: dict) -> str:
    """The error text of a failed request ("" when it succeeded)."""
    if not isinstance(packet, dict) or not packet.get("error"):
        return ""
    return f"{packet.get('error')}: {packet.get('message', '')}".strip()


def click_expression(selector: str) -> str:
    """Click-only JS for one CSS selector, answering a JSON verdict.

    `el.click()` is the honest primitive: it runs in the page's own context and
    adds nothing to it. A dispatched `MouseEvent` would carry `isTrusted:false`
    exactly like `.click()` does, so it would only add a fingerprint (design §5)
    — trusted input needs the OS, which is not what this channel is for.
    """
    wanted = json.dumps(str(selector or ""))
    return ("(() => { const el = document.querySelector(" + wanted + "); "
            "if (!el) return JSON.stringify({ok:false, why:'not found', selector:" + wanted + "}); "
            "el.click(); return JSON.stringify({ok:true, why:'clicked', selector:" + wanted + "}); })()")


def click_verdict(packet: dict) -> Dict[str, Any]:
    """The JSON verdict of `click_expression` ({} when the reply was not one)."""
    text = string_value(packet)
    if not text:
        return {}
    try:
        verdict = json.loads(text)
    except ValueError:
        return {}
    return verdict if isinstance(verdict, dict) else {}


def require_actor(actor: str) -> str:
    """Guard against an empty actor id, with the reason every caller can print."""
    if not actor:
        raise RdpError("no console actor for this tab (Firefox listed no evaluation target)", "protocol")
    return actor
