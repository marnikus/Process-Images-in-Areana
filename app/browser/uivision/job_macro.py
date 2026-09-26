"""Ui.Vision macros for one Firefox image job (I-65).

Clicks are XClick only (owner rule). `selectWindow` Value stays empty, so the
preexisting tab is reused and never opened. No close command is ever emitted —
cleanup must not close that tab. The file dialog gets the path by paste, never
by typing it. Per-phase values are baked into the file (there is no fourth
cmd_var); the tab selector still rides cmd_var3.

Imports: sibling macro + site_adapter selectors (RULE 21).
"""

from __future__ import annotations

import json
import sys

from ..site_adapter import get_selector
from . import job_probe, macro

MACRO_NAME = "Arena_ImageJob"
REPLY_VAR = "arenaJob"
REPLY_MARK = "ARENA_JOB="
_CLOSE_COMMANDS = frozenset({"close", "closewindow", "closetab"})


def css_target(selector: str) -> str:
    """Ui.Vision element locator for one CSS selector."""
    return "css=" + (selector or "")


def add_files_target() -> str:
    """Native click that opens the OS file dialog (the hidden input is not clicked)."""
    return css_target(get_selector("add_files_button").primary)


def remove_file_target() -> str:
    """Native click that drops a stale attachment preview."""
    return css_target(get_selector("remove_file_button").primary)


def send_target() -> str:
    """Native click on the enabled Send control — one command, one click."""
    return css_target(get_selector("send_button").primary)


def new_chat_target() -> str:
    """Native click on New Chat (same primary the Chrome reset uses)."""
    return css_target(get_selector("new_chat_button").primary)


def _open_tab() -> list:
    """Reuse the pooled tab. Empty Value is the never-open, never-close guarantee."""
    return [
        macro.command("selectWindow", macro.TAB_VAR, "",
                      "reuse the pooled tab — Value EMPTY, nothing is opened or closed"),
        macro.command("bringBrowserToForeground", "", "",
                      "native input needs Firefox visible and in front"),
    ]


def _echo(phase: str) -> list:
    """The phase answer lands in the savelog for the app to read back."""
    return [macro.command("echo", REPLY_MARK + "${" + REPLY_VAR + "}", "blue",
                          f"{phase} answer — read back from the savelog")]


def _store_script(script: str, note: str) -> list:
    """One executeScript whose return value is the echo variable."""
    return [macro.command("executeScript", script, REPLY_VAR, note)]


def _click(target: str, note: str) -> list:
    """RED find-rect (best effort) then one native XClick. Target also rides cmd_var2."""
    return [
        macro.command("executeScript", macro.FIND_RECT_JS, "",
                      "RED confirmation rectangle — best effort; XClick is the gate"),
        macro.command("XClick", target, "", note),
    ]


def _probe_rows() -> list:
    return _store_script(job_probe.build_snapshot_js(), "read attachment, prompt, send, results")


def _clear_rows() -> list:
    return _click(remove_file_target(), "remove a stale attachment (native click)") + _probe_rows()


# The dialog this process will drive. Tests pass a system explicitly.
_DIALOG_SYSTEMS = ("windows", "linux", "mac")
_SELECT_ALL = {"windows": "${KEY_CTRL+KEY_A}", "linux": "${KEY_CTRL+KEY_A}",
               "mac": "${KEY_CMD+KEY_A}"}
_PASTE_KEY = {"windows": "${KEY_CTRL+KEY_V}", "linux": "${KEY_CTRL+KEY_V}",
              "mac": "${KEY_CMD+KEY_V}"}
# Windows must NOT use this for a file path: the address bar treats an existing
# file as "How do you want to open this file?" and never selects it for us.
_LOCATION_KEY = {"linux": "${KEY_CTRL+KEY_L}", "mac": "${KEY_CMD+KEY_SHIFT+KEY_G}"}


def _dialog_system() -> str:
    """The OS file dialog the running app will actually see."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _require_upload_path(payload: dict) -> str:
    """One path. An empty name would make Enter confirm a highlighted stranger."""
    path = str((payload or {}).get("path") or "").strip()
    if not path or "\n" in path or "\r" in path:
        raise ValueError("upload path is empty or not a single path — refusing to confirm the dialog")
    return path


def _for_dialog(path: str, system: str) -> str:
    """Clipboard text. Windows gets a quoted `C:/...` path so spaces and `\\U` survive."""
    if system != "windows":
        return path
    native = path if path.startswith("\\\\") else path.replace("\\", "/")
    return '"' + native + '"'


def _pause(ms: str, note: str) -> dict:
    return macro.command("pause", ms, "", note)


def _xtype(keys: str, note: str) -> dict:
    return macro.command("XType", keys, "", note)


def file_dialog_rows(path: str, system: str) -> list:
    """Paste `path` into the open dialog and confirm. Never type it.

    Typing is what autocomplete turns into "file not found", so the image is
    never selected. Windows already focuses the filename box — no Alt+N (Czech
    locale), no Ctrl+L. Linux and mac open the location field first.
    """
    if system not in _DIALOG_SYSTEMS:
        raise ValueError(f"unsupported file-dialog system {system!r}")
    return (
        [_pause("1000", "file dialog focused before any key")]
        + _clipboard_rows(path, system)
        + _location_rows(system)
        + _paste_rows(system)
        + [_pause("400", "pasted path settles before Open")]
        + _confirm_rows(system)
        + [_pause("2000", "dialog closes and the attachment preview renders")]
    )


def _clipboard_rows(path: str, system: str) -> list:
    """`!stringescape` off first — a stored `\\Users` or `\\t` is otherwise eaten."""
    return [
        macro.command("store", "false", "!stringescape",
                      "literal path — \\t \\n \\Users must not become escapes"),
        macro.command("store", _for_dialog(path, system), "!clipboard",
                      "path the dialog will paste"),
    ]


def _location_rows(system: str) -> list:
    """Linux/mac only. Windows keeps the filename box, which already has focus."""
    key = _LOCATION_KEY.get(system)
    if not key:
        return []
    note = "GTK location bar" if system == "linux" else "Go to Folder"
    return [_xtype(key, note), _pause("300", "location field open")]


def _paste_rows(system: str) -> list:
    return [
        _xtype(_SELECT_ALL[system], "replace the focused field"),
        _xtype(_PASTE_KEY[system], "paste the path — typing it trips autocomplete"),
    ]


def _confirm_rows(system: str) -> list:
    """One Enter opens. macOS needs Go, then Open, while the panel is still up."""
    if system != "mac":
        return [_xtype("${KEY_ENTER}", "Open the pasted file")]
    return [
        _xtype("${KEY_ENTER}", "Go to the file"),
        _pause("400", "the file is selected, the panel stays open"),
        _xtype("${KEY_ENTER}", "Open"),
    ]


def _upload_rows(payload: dict) -> list:
    path = _require_upload_path(payload)
    return (
        _click(add_files_target(), "open the OS file dialog (native click, never DOM click)")
        + file_dialog_rows(path, _dialog_system())
        + _probe_rows()
    )


def _prompt_rows(payload: dict) -> list:
    return _store_script(job_probe.build_insert_js(str(payload.get("prompt") or "")),
                         "insert the prompt (Chrome value-setter) and read it back")


def _submit_rows() -> list:
    return _click(send_target(), "send exactly once (native click)") + _probe_rows()


def _download_rows(payload: dict) -> list:
    return _store_script(job_probe.build_download_js(str(payload.get("src") or "")),
                         "fetch the correlated result in the page (cookies included)")


def _new_chat_rows() -> list:
    return _click(new_chat_target(), "New Chat after a saved job (native click)") + _probe_rows()


_ROWS = {
    "probe": lambda _payload: _probe_rows(),
    "clear": lambda _payload: _clear_rows(),
    "upload": _upload_rows,
    "prompt": _prompt_rows,
    "submit": lambda _payload: _submit_rows(),
    "download": _download_rows,
    "new_chat": lambda _payload: _new_chat_rows(),
}


def phase_rows(phase: str, payload: dict | None = None) -> list:
    """Commands for one phase. Unknown phases raise — never a silent no-op (RULE 4)."""
    builder = _ROWS.get(phase)
    if builder is None:
        raise ValueError(f"unknown image-job phase {phase!r}")
    return builder(payload or {})


def refuse_tab_close(commands) -> None:
    """The preexisting tab must survive the macro (no close, no selectWindow open)."""
    for row in commands:
        name = str(row.get("Command") or "").strip().lower()
        if name in _CLOSE_COMMANDS:
            raise ValueError("macro must not close the preexisting Firefox tab")
        if name == "selectwindow" and str(row.get("Value") or "") != "":
            raise ValueError("selectWindow Value must stay empty — never open a page")
        if "window.close" in json.dumps(row):
            raise ValueError("macro must not close the preexisting Firefox tab")


def build_commands(phase: str, payload: dict | None = None) -> list:
    """Open-tab guard + the phase + the savelog echo. DOM clicks are refused."""
    commands = _open_tab() + phase_rows(phase, payload) + _echo(phase)
    macro.refuse_dom_clicks(commands)
    refuse_tab_close(commands)
    return commands


def xclick_targets(commands) -> list:
    """XClick targets in order — submit must contribute exactly one."""
    return [row.get("Target") or "" for row in commands if row.get("Command") == "XClick"]


def build_job_macro(phase: str, payload: dict | None = None) -> dict:
    """The macro document written to `<home>/macros/Arena_ImageJob.json`."""
    return {"Name": MACRO_NAME, "CreationDate": macro.creation_date(),
            "Commands": build_commands(phase, payload)}
