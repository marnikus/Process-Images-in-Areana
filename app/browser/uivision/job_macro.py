"""Ui.Vision macros for one Firefox image job (I-65).

Clicks are XClick only (owner rule). `selectWindow` Value stays empty, so the
preexisting tab is reused and never opened. No close command is ever emitted —
cleanup must not close that tab. The Windows file dialog is driven from the
queue path by `file_dialog`, not by typing. Per-phase values are baked into
the file (there is no fourth cmd_var); the tab selector still rides cmd_var3.

Imports: sibling macro, file_dialog, site_adapter selectors (RULE 21).
"""

from __future__ import annotations

import json
import sys

from ..site_adapter import get_selector
from . import file_dialog, job_probe, macro

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


def _dialog_system() -> str:
    """The OS file dialog the running app will actually see."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def file_dialog_rows(path: str, system: str) -> list:
    """Dialog commands after the plus click. Windows waits for the Win32 filler."""
    return file_dialog.rows(path, system)


def _upload_rows(payload: dict) -> list:
    path = file_dialog.require_path(payload)
    return (
        _click(add_files_target(), "open the OS file dialog (native click, never DOM click)")
        + file_dialog.rows(path, _dialog_system())
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
