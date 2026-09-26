"""Drive the OS File Upload dialog with the image-queue path (I-65).

XType never reached the live dialog: it stayed on Desktop with an empty File
name box. On Windows the upload thread sets that box from the queued
absolute path and clicks Open — no clipboard, no locale shortcut. Other
systems still paste, because this process is not their dialog.

Imports: sibling macro only. No Qt.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import macro

SYSTEMS = ("windows", "linux", "mac")
WAIT_MS = "8000"
FILENAME_ID = 1148
FILENAME_FALLBACK = 1152
IDOK = 1
WM_SETTEXT = 0x000C
WM_COMMAND = 0x0111
DIALOG_CLASS = "#32770"
DIALOG_TITLE = "File Upload"
RESULT_NAME = "queued_image_result.txt"
_SELECT_ALL = {"linux": "${KEY_CTRL+KEY_A}", "mac": "${KEY_CMD+KEY_A}"}
_PASTE_KEY = {"linux": "${KEY_CTRL+KEY_V}", "mac": "${KEY_CMD+KEY_V}"}
_LOCATION_KEY = {"linux": "${KEY_CTRL+KEY_L}", "mac": "${KEY_CMD+KEY_SHIFT+KEY_G}"}


def require_path(payload: dict) -> str:
    """One queued path. Empty would make Open confirm a highlighted stranger."""
    path = str((payload or {}).get("path") or "").strip()
    if not path or "\n" in path or "\r" in path:
        raise ValueError("upload path is empty or not a single path — refusing to confirm the dialog")
    return path


def result_file(home) -> Path:
    """Where the filler writes ok or a named reason."""
    return Path(home) / RESULT_NAME


def read_result(path: Path) -> str:
    """'' when the filler has not written yet."""
    if not Path(path).is_file():
        return ""
    return Path(path).read_text(encoding="utf-8").strip()


def start_fill(path: str, result: Path) -> threading.Thread:
    """Poll for the open dialog and select `path` (the queue absolute path)."""
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text("waiting", encoding="utf-8")
    worker = threading.Thread(
        target=open_queued_file, kwargs={"path": path, "result_path": str(result)},
        name="file-dialog", daemon=True)
    worker.start()
    return worker


def rows(path: str, system: str) -> list:
    """Commands after the plus click. Windows waits; the thread drives Explorer."""
    if system not in SYSTEMS:
        raise ValueError(f"unsupported file-dialog system {system!r}")
    if system == "windows":
        return [_pause(WAIT_MS, "queued image: " + path)]
    return _key_rows(path, system)


def open_queued_file(path: str, result_path: str = "", port=None) -> str:
    """Put the queued path in File name and click Open. '' on success."""
    reason = _missing(path) or _select(path, port or Win32Dialog())
    if result_path:
        Path(result_path).write_text(reason or "ok", encoding="utf-8")
    return reason


def _missing(path: str) -> str:
    if not path or not os.path.isfile(path):
        return f"queued image path does not exist: {path}"
    return ""


def _select(path: str, port) -> str:
    """Write the queue path into File name, then click Open."""
    dlg = port.wait(40)
    if not dlg:
        return "File Upload dialog was not open"
    full = os.path.normpath(path)
    if not port.set_filename(dlg, full):
        return "file name box not found"
    if not port.click_open(dlg):
        return "Open button not found"
    return ""


class Win32Dialog:
    """The live File Upload window. Control 1148 is File name; 1 is Open."""

    def __init__(self, user32=None):
        self._u = user32 if user32 is not None else _user32()

    def wait(self, seconds: float) -> int:
        deadline = time.time() + seconds
        while time.time() < deadline:
            hwnd = self.find()
            if hwnd:
                return hwnd
            time.sleep(0.2)
        return 0

    def find(self) -> int:
        for title in (DIALOG_TITLE, "Open"):
            hwnd = self._u.FindWindowW(DIALOG_CLASS, title)
            if hwnd:
                return int(hwnd)
        return int(self._u.FindWindowW(None, DIALOG_TITLE) or 0)

    def set_filename(self, dlg: int, text: str) -> bool:
        combo = self._item(dlg, FILENAME_ID) or self._item(dlg, FILENAME_FALLBACK)
        edit = self._inner_edit(combo) if combo else 0
        target = edit or combo or self._inner_edit(dlg)
        if not target:
            return False
        _send_text(self._u, target, text)
        return True

    def click_open(self, dlg: int) -> bool:
        button = self._item(dlg, IDOK)
        if not button:
            return False
        _send_ok(self._u, dlg, button)
        return True

    def alive(self, dlg: int) -> bool:
        return bool(self._u.IsWindow(dlg))

    def _item(self, dlg: int, control_id: int) -> int:
        return int(self._u.GetDlgItem(dlg, control_id) or 0)

    def _inner_edit(self, parent: int) -> int:
        if not parent:
            return 0
        return int(self._u.FindWindowExW(parent, None, "Edit", None) or 0)


def _user32():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    _bind(user32, wintypes)
    return user32


def _bind(user32, wintypes) -> None:
    import ctypes
    specs = (
        ("FindWindowW", [wintypes.LPCWSTR, wintypes.LPCWSTR], wintypes.HWND),
        ("GetDlgItem", [wintypes.HWND, ctypes.c_int], wintypes.HWND),
        ("FindWindowExW", [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR], wintypes.HWND),
        ("IsWindow", [wintypes.HWND], wintypes.BOOL),
    )
    for name, args, rest in specs:
        fn = getattr(user32, name, None)
        if fn is not None and hasattr(fn, "argtypes"):
            fn.argtypes = args
            fn.restype = rest


def _send_text(user32, hwnd: int, text: str) -> None:
    from ctypes import wintypes
    fn = user32.SendMessageW
    if hasattr(fn, "argtypes"):
        fn.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
        fn.restype = wintypes.LPARAM
    fn(hwnd, WM_SETTEXT, 0, text)


def _send_ok(user32, dlg: int, button: int) -> None:
    from ctypes import wintypes
    fn = user32.SendMessageW
    if hasattr(fn, "argtypes"):
        fn.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        fn.restype = wintypes.LPARAM
    fn(dlg, WM_COMMAND, IDOK, button)


def _pause(ms: str, note: str) -> dict:
    return macro.command("pause", ms, "", note)


def _xtype(keys: str, note: str) -> dict:
    return macro.command("XType", keys, "", note)


def _desktop(on: bool) -> dict:
    note = "keystrokes go to the OS file dialog" if on else "probe runs in the page again"
    return macro.command("XDesktopAutomation", "true" if on else "false", "", note)


def _key_rows(path: str, system: str) -> list:
    """Linux/mac paste. Windows does not use this — the live dialog ignored it."""
    return (
        [_pause("1200", "file dialog painted before any key"), _desktop(True),
         _pause("400", "desktop automation owns the dialog")]
        + _clipboard(path)
        + _focus(system)
        + [_xtype(_SELECT_ALL[system], "replace the focused field"),
           _xtype(_PASTE_KEY[system], "paste the path")]
        + [_pause("400", "pasted path settles before Open")]
        + _confirm(system)
        + [_desktop(False), _pause("1500", "dialog closed, attachment preview renders")]
    )


def _clipboard(path: str) -> list:
    return [
        macro.command("store", "false", "!stringescape", "literal path"),
        macro.command("store", path, "!clipboard", "path the dialog will paste"),
    ]


def _focus(system: str) -> list:
    key = _LOCATION_KEY[system]
    note = "GTK location bar" if system == "linux" else "Go to Folder"
    return [_xtype(key, note), _pause("300", "location field open")]


def _confirm(system: str) -> list:
    if system != "mac":
        return [_xtype("${KEY_ENTER}", "Open the pasted file")]
    return [
        _xtype("${KEY_ENTER}", "Go to the file"),
        _pause("400", "the file is selected, the panel stays open"),
        _xtype("${KEY_ENTER}", "Open"),
    ]
