"""Ui.Vision macro JSON — the commands the extension executes.

A Ui.Vision macro is a JSON document of `{Command, Target, Value}` rows. This
module builds them, so the app never ships a hand-edited macro file that can
drift from the code that launches it.

**XClick, never Click.** `Click` is a DOM-level event: the page sees
`isTrusted: false`, which is exactly the automation signal this whole feature
exists to avoid. `XClick` drives the real OS mouse cursor through the RealUser
XModule, so the event is indistinguishable from a human's. `build_macro`
therefore refuses to emit a `Click` at all — the rule is enforced by
construction rather than left to reviewers (`FORBIDDEN_COMMANDS`).

Two consequences of using the real cursor, both reflected here:

* XClick can only hit what is **visible**, so a scroll step precedes the click.
* XType has no target — it types into whatever has focus — so it must always
  follow an XClick that sets that focus.

Layer: browser leaf — pure data; no I/O, no Qt, no app imports.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

__all__ = ["MacroStep", "build_macro", "macro_json", "new_chat_macro",
           "FORBIDDEN_COMMANDS", "NEW_CHAT_XPATH"]

# DOM-level commands: they produce isTrusted:false and must never be generated.
FORBIDDEN_COMMANDS = frozenset({"click", "clickat", "type", "sendkeys"})

# The Arena sidebar "New Chat" entry: an <a> whose <span> holds the label.
NEW_CHAT_XPATH = "xpath=//a[span[text()='New Chat']]"


class MacroStep:
    """One `{Command, Target, Value}` row."""

    def __init__(self, command: str, target: str = "", value: str = ""):
        self.command = str(command or "").strip()
        self.target = str(target or "")
        self.value = str(value or "")

    def as_row(self) -> Dict[str, str]:
        return {"Command": self.command, "Target": self.target, "Value": self.value}


def _reject_dom_clicks(steps: List[MacroStep]) -> None:
    """Fail loudly if a DOM-level command slipped in (the isTrusted rule)."""
    for step in steps:
        if step.command.lower() in FORBIDDEN_COMMANDS:
            raise ValueError(
                f"'{step.command}' is a DOM-level command (isTrusted:false). "
                f"Use the X-prefixed native command instead (XClick / XType).")


def build_macro(name: str, steps: List[MacroStep]) -> Dict[str, Any]:
    """A macro document; raises if any step would produce an untrusted event."""
    _reject_dom_clicks(steps)
    return {"Name": str(name or "Untitled"), "CreationDate": "",
            "Commands": [s.as_row() for s in steps]}


def macro_json(name: str, steps: List[MacroStep]) -> str:
    """The macro as the JSON text Ui.Vision imports."""
    return json.dumps(build_macro(name, steps), indent=2, ensure_ascii=False)


def new_chat_macro(url: str = "", target: str = "", name: str = "Python_XClick_Demo",
                   settle_seconds: float = 2.0) -> Dict[str, Any]:
    """The framework proof: open Arena, scroll the element in, XClick it, echo done.

    `url` and `target` default to the macro's own `${!cmd_var1}` / `${!cmd_var2}`,
    so the *same stored macro* is reusable — the app passes both on the command
    line instead of rewriting the macro per run.

    A plain `click` is never used. `storeText` only *reads* the element (it does
    not dispatch an event) and doubles as the "is it there?" check before the
    native click.
    """
    page = url or "${!cmd_var1}"
    element = target or "${!cmd_var2}"
    pause_ms = str(int(max(settle_seconds, 0) * 1000))
    return build_macro(name, [
        MacroStep("open", page),
        MacroStep("pause", pause_ms),
        MacroStep("storeText", element, "found_label"),   # read-only presence probe
        MacroStep("XClick", element),                     # native OS click (isTrusted:true)
        MacroStep("pause", "500"),
        MacroStep("echo", "done"),
    ])
