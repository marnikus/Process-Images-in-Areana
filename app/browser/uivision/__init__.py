"""Firefox automation through the Ui.Vision RPA extension — no debugger, no driver.

Firefox stays a **normal browser**: it is launched with no automation flags at
all, and the work happens inside a signed extension that drives the real OS
mouse and keyboard through the XModules. Websites therefore see `isTrusted:
true` input from an ordinary browser session.

Why this replaced the DevTools RDP approach (I-62…I-64): that path needed
`--start-debugger-server`, which made Firefox prompt to authorise every
connection and marked the window as remotely controlled. Ui.Vision needs no
port at all.

Files:

* `command_url` — the autorun `ui.vision.html?…` URL (the Command Line API)
* `macro`       — macro JSON; XClick only, DOM `Click` refused by construction
* `run_log`     — the `savelog` file, the only completion signal there is
* `runner`      — launch a normal Firefox tab, then poll for the verdict

Requires the Ui.Vision extension **and** the RealUser XModule (XClick/XType are
native OS input and do not work without it), plus a visible, unlocked desktop.

Layer: browser — leaf modules only; no Qt, no services, no panels.
"""

from __future__ import annotations

from .command_url import (STORAGE_BROWSER, STORAGE_XFILE, MacroRun, build_autorun_url,
                          to_file_url)
from .macro import (FORBIDDEN_COMMANDS, NEW_CHAT_XPATH, MacroStep, build_macro, macro_json,
                    new_chat_macro)
from .run_log import FAILED, OK, PENDING, RunVerdict, clear_log, parse_log, read_verdict
from .runner import (DEFAULT_TIMEOUT_S, LAUNCH_BANNED_FLAGS, MacroOutcome, find_firefox,
                     launch_argv, poll_verdict, run_macro)

__all__ = [
    "MacroRun", "build_autorun_url", "to_file_url", "STORAGE_BROWSER", "STORAGE_XFILE",
    "MacroStep", "build_macro", "macro_json", "new_chat_macro", "FORBIDDEN_COMMANDS",
    "NEW_CHAT_XPATH",
    "RunVerdict", "parse_log", "read_verdict", "clear_log", "PENDING", "OK", "FAILED",
    "MacroOutcome", "run_macro", "poll_verdict", "launch_argv", "find_firefox",
    "LAUNCH_BANNED_FLAGS", "DEFAULT_TIMEOUT_S",
]
