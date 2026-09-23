"""The Ui.Vision macro builder — the framework test `Python_XClick_Demo` (I-63).

The owner's critical rule: the click is **XClick** (native OS input through the
Desktop Automation XModule, `isTrusted: true`), never the DOM-level `click` —
so the builder refuses to emit any JS-level mouse command and a test pins that.
`bringBrowserToForeground` runs before the XClick because native input lands
where the OS pointer is (the official demo macros pair the two).

The macro reuses the run's tab instead of blindly navigating: `selectWindow`
with `${!cmd_var3}` activates the existing tab (`title=*pattern*`, wildcards
per the selectWindow docs); when no tab matches, `!errorignore` + `!statusOK`
fall through to `selectWindow | tab=open`, which opens the run's URL in a
fresh tab. A blank pattern skips the probe (`tab=open` straight away).

Per-run values ride the command line instead of the file: `${!cmd_var1}` is the
URL, `${!cmd_var2}` the XClick target and `${!cmd_var3}` the tab target, so the
macro on disk stays generic and each launch passes its own values in the URL.

The JSON shape is Ui.Vision's own (`src/common/convert_utils.js toJSONString`):
`{"Name", "CreationDate", "Commands": [{"Command", "Target", "Value",
"Description"}]}` — hard-drive storage keeps it at `<home>/macros/<Name>.json`.
"""

from __future__ import annotations

import json
import re
from datetime import date

DEFAULT_MACRO_NAME = "Python_XClick_Demo"
URL_VAR = "${!cmd_var1}"
TARGET_VAR = "${!cmd_var2}"
TAB_VAR = "${!cmd_var3}"
OPEN_TAB = "tab=open"
STATUS_FALSE = "${!statusOK} == false"
DONE_TEXT = "done — XClick fired (native OS input)"

# DOM-level mouse commands are banned by the owner's rule (they synthesize
# isTrusted:false events); XClick is the only click this macro may contain.
FORBIDDEN_COMMANDS = frozenset({
    "click", "clickandwait", "clickat", "doubleclick", "contextmenu",
    "mouseover", "mousedown", "mouseup",
})

# The name is a file path segment and a URL parameter — one safe grammar.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]{0,63}$")


def validate_macro_name(name) -> str:
    """A macro name that is safe as a file name and URL value (ValueError otherwise)."""
    text = (name or "").strip()
    if not NAME_PATTERN.match(text):
        raise ValueError(
            f"macro name {text!r} is not allowed — letters, digits, '_' and '-' only "
            f"(it becomes <home>/macros/<Name>.json)")
    return text


def command(name: str, target: str = "", value: str = "", description: str = "") -> dict:
    """One Ui.Vision command row."""
    return {"Command": name, "Target": target, "Value": value, "Description": description}


def refuse_dom_clicks(commands) -> None:
    """The critical rule as a gate: no DOM-level mouse command may ride a macro."""
    names = {str(c.get("Command") or "").strip().lower() for c in commands}
    bad = sorted(names & FORBIDDEN_COMMANDS)
    if bad:
        raise ValueError(f"DOM-level mouse commands are forbidden (use XClick): {', '.join(bad)}")


def build_commands(pause_ms=3000, done_text: str = DONE_TEXT) -> list:
    """Reuse the run's tab (else open it) → foreground → pause → XClick → echo done."""
    commands = [
        command("store", "true", "!statusOK",
                "reset the status latch — the tab probe below sets it"),
        command("store", "true", "!errorignore",
                "a missing tab must fall through to open, not stop the macro"),
        command("selectWindow", TAB_VAR, URL_VAR,
                "reuse the tab matching cmd_var3 (title=*pattern*), or open cmd_var1 "
                "in a fresh tab when cmd_var3 is tab=open"),
        command("if", STATUS_FALSE, "",
                "no matching tab — open the run's URL in a fresh tab"),
        command("selectWindow", OPEN_TAB, URL_VAR,
                "fresh tab at the run's URL (only when the probe above missed)"),
        command("end", "", "", "the tab is ready either way"),
        command("store", "false", "!errorignore",
                "strict again — a failed XClick must fail the run, not pass silent"),
        command("bringBrowserToForeground", "", "",
                "native input needs Firefox visible and in front (owner's critical rule)"),
        command("pause", str(int(pause_ms)), "", "let the page settle before the OS click"),
        command("XClick", TARGET_VAR, "",
                "native OS click on the target passed on the command line (never DOM click)"),
        command("echo", done_text, "green", "completion marker — it lands in the savelog file"),
    ]
    refuse_dom_clicks(commands)
    return commands


def creation_date(today=None) -> str:
    """Ui.Vision's own date format: `YYYY-M-D`, no zero padding (toJSONString)."""
    day = today or date.today()
    return f"{day.year}-{day.month}-{day.day}"


def build_macro(name: str = DEFAULT_MACRO_NAME, pause_ms=3000,
                done_text: str = DONE_TEXT, today=None) -> dict:
    """The macro document Ui.Vision reads from `<home>/macros/<Name>.json`."""
    return {"Name": validate_macro_name(name),
            "CreationDate": creation_date(today),
            "Commands": build_commands(pause_ms, done_text)}


def to_json(macro: dict) -> str:
    """The macro as the extension stores it (readable, stable key order)."""
    return json.dumps(macro, ensure_ascii=False, indent=2) + "\n"
