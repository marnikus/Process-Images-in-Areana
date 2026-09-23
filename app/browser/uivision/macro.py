"""The Ui.Vision macro builder — the framework test `Python_XClick_Demo` (I-63).

The owner's critical rule: the click is **XClick** (native OS input through the
Desktop Automation XModule, `isTrusted: true`), never the DOM-level `click` —
so the builder refuses to emit any JS-level mouse command and a test pins that.
`bringBrowserToForeground` runs before the XClick because native input lands
where the OS pointer is (the official demo macros pair the two).

The macro reuses the run's tab and NEVER opens or navigates anywhere (the
owner's rule: the page is already open): `selectWindow` with `${!cmd_var3}`
activates the existing tab (`title=*pattern*`) and fails loudly when it is
gone — no fallback, no fresh tab. `highlight` then flashes the found element
yellow (the visual confirmation, before any click), `pause` lets the page
settle while it shows, and `XClick` fires the native click. The last two
steps close the autorun tab the launch unavoidably opened (`tab=0` is the tab
the macro started in — deterministic because the launch URL pins
`continueInLastUsedTab=0`), so the run leaves net zero new pages; the cleanup
rides `!errorignore` so it can never fail an otherwise good run.

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
TAB_HOME = "tab=0"
TAB_CLOSE = "TAB=CLOSE"
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
    """Use the open tab → flash the element → XClick → echo done → close the autorun tab."""
    commands = [
        command("selectWindow", TAB_VAR, "",
                "activate the run's already-open tab (title=*pattern*) — fails loudly "
                "when it is gone; this macro never opens pages"),
        command("bringBrowserToForeground", "", "",
                "native input needs Firefox visible and in front (owner's critical rule)"),
        command("highlight", TARGET_VAR, "",
                "flash the found element yellow — the visual confirmation before the click"),
        command("pause", str(int(pause_ms)), "",
                "let the page settle while the highlight shows"),
        command("XClick", TARGET_VAR, "",
                "native OS click on the target passed on the command line (never DOM click)"),
        command("echo", done_text, "green", "completion marker — it lands in the savelog file"),
        command("store", "true", "!errorignore",
                "cleanup must never fail an otherwise good run"),
        command("selectWindow", TAB_HOME, "",
                "back to the tab the macro started in (the autorun tab)"),
        command("selectWindow", TAB_CLOSE, "",
                "close the autorun tab — the run leaves net zero new pages"),
        command("store", "false", "!errorignore", "strict again (the macro ends here)"),
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
