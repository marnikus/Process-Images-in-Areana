"""The Windows OS file dialog opened by the Firefox attach XClick (live fix 2026-09-26).

Owns only the macro rows that run while the native "Open" dialog is up; the
XClick that opens it and the preview probe that verifies the result stay in
`job_macros.attach_macro`. Imports `macro` only (no services, no Qt).

Owner's live run: the dialog opened, but its File name box stayed empty and the
dialog stayed open. Causes and the rule each one sets:

* Ui.Vision XType in browser mode never reaches the OS window → every key row
  runs inside `XDesktopAutomation true … false`; page probes run outside it.
* `!StringEscape` (default on) turns `\\u` `\\t` `\\n` of a Windows path into
  escapes, and a path typed char by char is rewritten by the dialog's
  autocomplete → the path is stored in `!clipboard` (escapes off, quoted, native)
  and pasted; it is never XType'd.
* The name box is not focused on open → Alt+N ("File name" / "Název souboru").
* Firefox's dialog ignores a bare Enter (Ui.Vision forum) → Open = Alt+O; Enter
  and ESC are sent only while the dialog is provably still up (the page has no
  focus and our preview is absent) so a stray key never lands in the page,
  where Enter on the focused "Add files" button would open a second dialog.
"""

from __future__ import annotations

import json

from . import macro

OPEN_VAR = "dialogOpen"      # 1 = the dialog is still up after Open


def dialog_path(path) -> str:
    """The clipboard text: the native path in quotes (spaces survive; stored with escapes off)."""
    text = str(path or "").strip()
    if not text or any(ch in text for ch in '\r\n"') or "${" in text:
        raise ValueError(f"upload path cannot go through the file dialog: {text!r}")
    return '"' + text + '"'


def still_open_js(staged_name: str) -> str:
    """executeScript body: 1 while the OS dialog holds the focus and our preview is absent."""
    sel = json.dumps(f'img[alt="{staged_name}"]')
    return f"return document.hasFocus() || document.querySelector({sel}) ? 0 : 1"


def _desktop(on: bool) -> dict:
    note = "keys go to the OS file dialog" if on else "back to the page (browser mode)"
    return macro.command("XDesktopAutomation", "true" if on else "false", "", note)


def _keys(*pairs) -> list:
    return [macro.command("XType", key, "", note) for key, note in pairs]


def _clipboard(path) -> list:
    return [macro.command("store", "false", "!StringEscape", "literal path: no \\u \\t \\n escapes"),
            macro.command("store", dialog_path(path), "!clipboard", "the path the dialog pastes"),
            macro.command("store", "true", "!StringEscape", "default again for the rest")]


def fill_and_open(path, staged_name: str) -> list:
    """Paste the staged path into File name, press Open; Enter once more only if still up."""
    return (_clipboard(path)
            + [macro.command("pause", "1500", "", "let the OS file dialog open"), _desktop(True)]
            + _keys(("${KEY_ALT+KEY_N}", "focus File name"), ("${KEY_CTRL+KEY_A}", "replace its text"),
                    ("${KEY_CTRL+KEY_V}", "paste the path"), ("${KEY_ALT+KEY_O}", "Open"))
            + [_desktop(False), macro.command("pause", "1500", "", "dialog closes, preview renders"),
               macro.command("executeScript", still_open_js(staged_name), OPEN_VAR, "dialog still up?"),
               macro.command("if_v2", "${" + OPEN_VAR + "} == 1", "", "Alt+O missed (other locale)"),
               _desktop(True), *_keys(("${KEY_ENTER}", "confirm the pasted path")), _desktop(False),
               macro.command("pause", "1500", "", ""), macro.command("end", "", "", "")])


def escape_when(condition: str) -> list:
    """Close a dialog left open (ESC in desktop mode), only when `condition` holds."""
    return [macro.command("if_v2", condition, "", "the dialog may still be open"),
            _desktop(True), *_keys(("${KEY_ESC}", "close the leftover dialog")), _desktop(False),
            macro.command("end", "", "", "")]
