"""Ui.Vision Command Line API — the autorun URL (pure, no I/O).

Ui.Vision has no socket and no RPC. A macro is started by opening the
extension's `ui.vision.html` page with GET parameters; the extension reads them
and runs. That URL *is* the API, so building it correctly is the whole contract:

    file:///D:/rpa/ui.vision.html?macro=X&direct=1&closeRPA=0&savelog=C:/log.txt

Parameters this module owns (from the official Command Line API):

* ``macro``      — the macro to run
* ``direct=1``   — skip the "Do you want to run this macro?" prompt
* ``closeRPA``   — close the RPA window when done (**default is 1**; we send 0
  so the log stays readable and the extension is not torn down mid-poll)
* ``closeBrowser`` — default 0; we never close the user's browser
* ``savelog``    — write the run log to a path. With a *full* path the log is
  written directly instead of triggering a download — the reason we always
  pass an absolute path
* ``cmd_var1..3`` — values the macro reads as `${!cmd_var1..3}`
* ``storage``    — `browser` (HTML5 storage) or `xfile` (hard drive)

Two encoding rules are load-bearing. The file path must be a `file:///` URL, or
the browser reports "file not found" because it treats the `?…` as part of the
name. And every value must be percent-encoded — an XPath target is full of
`/`, `[`, `'` and `=`, any of which would otherwise split the query string.

Layer: browser leaf — pure string building; no subprocess, no Qt, no app imports.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

__all__ = ["MacroRun", "build_autorun_url", "to_file_url", "STORAGE_BROWSER",
           "STORAGE_XFILE"]

STORAGE_BROWSER = "browser"
STORAGE_XFILE = "xfile"
_MAX_CMD_VARS = 3  # the extension exposes exactly ${!cmd_var1..3}


def to_file_url(path: Any) -> str:
    """A local path as a `file:///` URL — required, or the GET params break.

    Windows `C:\\rpa\\ui.vision.html` → `file:///C:/rpa/ui.vision.html`.
    An already-formed `file://` or `http(s)://` URL is passed through.
    """
    text = str(path or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("file://", "http://", "https://")):
        return text
    normalised = PurePath(text).as_posix().replace("\\", "/").lstrip("/")
    return "file:///" + quote(normalised, safe="/:")


class MacroRun:
    """One macro invocation: what to run, with which values, logging where."""

    def __init__(self, macro: str, html_path: str, log_path: str = "",
                 cmd_vars: Optional[List[str]] = None):
        self.macro = str(macro or "").strip()
        self.html_path = str(html_path or "").strip()
        self.log_path = str(log_path or "").strip()
        self.cmd_vars = [str(v) for v in (cmd_vars or [])][:_MAX_CMD_VARS]

    @property
    def is_runnable(self) -> bool:
        """Both the macro name and the extension page are known."""
        return bool(self.macro and self.html_path)

    def missing(self) -> List[str]:
        """What stops this run, in words the operator can act on."""
        gaps = []
        if not self.macro:
            gaps.append("no macro name")
        if not self.html_path:
            gaps.append("no ui.vision.html path")
        return gaps


def _query(run: MacroRun, storage: str, close_rpa: bool) -> Dict[str, str]:
    """Every GET parameter for this run, in a stable order."""
    params: Dict[str, str] = {"macro": run.macro, "direct": "1",
                              "closeRPA": "1" if close_rpa else "0",
                              "closeBrowser": "0", "storage": storage}
    for index, value in enumerate(run.cmd_vars, start=1):
        params[f"cmd_var{index}"] = value
    if run.log_path:
        params["savelog"] = run.log_path  # absolute → written directly, not downloaded
    return params


def build_autorun_url(run: MacroRun, storage: str = STORAGE_BROWSER,
                      close_rpa: bool = False) -> str:
    """The full autorun URL, percent-encoded; '' when the run is not runnable.

    Empty means "nothing to run" and is never a half-built URL (RULE 4).
    """
    if not run.is_runnable:
        return ""
    return f"{to_file_url(run.html_path)}?{urlencode(_query(run, storage, close_rpa))}"
