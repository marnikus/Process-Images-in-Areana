"""The savelog file — Ui.Vision's official completion contract.

When a run with `savelog=<path>` finishes, the extension writes one text file
(`src/index.js genPlayerPlayCallback`): **line 1** is `Status=OK` or
`Status=Error: <message>`, **line 2** is `###`, and the run's log lines follow.
With the XModules installed a full-path `savelog` is written straight to disk;
without them it lands in the browser's download folder (the panel says which).

Polling stops on content, on the deadline or on the user's Stop — and reports
WHICH of the three happened (RULE 4: timeout, stopped and corrupt are
different answers, never one invented "failed").
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

OK_PREFIX = "Status=OK"
ERROR_PREFIX = "Status=Error:"
SEPARATOR = "###"
MAX_LINES = 60
POLL_SECONDS = 0.5


@dataclass(frozen=True)
class LogResult:
    """One run's verdict: ok | error | timeout | stopped | corrupt."""

    kind: str
    message: str = ""
    lines: tuple = ()

    @property
    def done(self) -> bool:
        """True when the extension itself answered (success or named failure)."""
        return self.kind in ("ok", "error")


def _tail(text: str) -> tuple:
    """The run log under the `###` separator, capped (last lines are the news)."""
    rows = [line for line in (text or "").splitlines()[1:] if line.strip() != SEPARATOR]
    return tuple(row.strip() for row in rows[-MAX_LINES:] if row.strip())


def parse_status(text: str):
    """First-line contract → LogResult, or None while the file has no content yet."""
    body = (text or "").strip()
    if not body:
        return None
    first = body.splitlines()[0].strip()
    lines = _tail(text)
    if first.startswith(OK_PREFIX):
        return LogResult(kind="ok", message=first[len(OK_PREFIX):].strip() or "macro completed",
                         lines=lines)
    if first.startswith(ERROR_PREFIX):
        return LogResult(kind="error",
                         message=first[len(ERROR_PREFIX):].strip() or "macro failed",
                         lines=lines)
    return LogResult(kind="corrupt", message=f"unreadable status line: {first[:120]}",
                     lines=lines)


def _read(path) -> str:
    """The file's text ('' while missing or unreadable — an absent log is a wait)."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


async def poll_log(path, deadline: float, sleep=None, stop=None) -> LogResult:
    """Wait for the savelog file to answer; parse it or name why nothing came.

    `sleep`/`stop` are the test and user seams: `stop()` is checked every
    iteration (RULE 7 — Stop means stop), `deadline` is a `time.time()` stamp.
    """
    nap = sleep or asyncio.sleep
    stopped = stop or (lambda: False)
    while True:
        result = parse_status(_read(path))
        if result is not None:
            return result
        if stopped():
            return LogResult(kind="stopped", message="stopped before the log file answered")
        if time.time() >= deadline:
            return LogResult(kind="timeout",
                             message=f"no status line in {path} within the deadline — "
                                     f"check that the Ui.Vision extension ran the macro")
        await nap(POLL_SECONDS)
