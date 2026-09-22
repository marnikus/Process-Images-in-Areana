"""Reading a Ui.Vision run log — the only completion signal available.

There is no callback and no exit code: the extension runs in the browser and
reports by writing `savelog=<path>`. So "did the macro finish?" is answered by
polling that file, and this module owns how it is read.

Parsing rules taken from the log format Ui.Vision writes:

* The final line is `[status] Macro completed` / `Status=OK`, or an `[error]`.
* A log that exists but has no verdict line yet means **still running** — not
  failure. Distinguishing "no verdict yet" from "failed" is the whole point
  (RULE 4); conflating them makes every slow macro look broken.
* The file may be read *while* the extension is writing it, so a truncated
  read is normal and must not raise.

Layer: browser leaf — one file read, no subprocess, no Qt, no app imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

__all__ = ["RunVerdict", "PENDING", "OK", "FAILED", "parse_log", "read_verdict",
           "clear_log"]

PENDING = "pending"
OK = "ok"
FAILED = "failed"

_OK_MARKERS = ("status=ok", "macro completed", "[status] macro completed")
_ERROR_PREFIXES = ("[error]", "error:")


@dataclass(frozen=True)
class RunVerdict:
    """The outcome so far: `state` plus the log lines that decided it."""

    state: str = PENDING
    message: str = ""
    lines: List[str] = None  # type: ignore[assignment]

    @property
    def is_done(self) -> bool:
        """The macro reached a verdict — stop polling."""
        return self.state in (OK, FAILED)

    @property
    def ok(self) -> bool:
        return self.state == OK


def _verdict_of(line: str) -> Optional[str]:
    """OK / FAILED if this line is a verdict, else None."""
    lowered = line.strip().lower()
    if not lowered:
        return None
    if any(lowered.startswith(p) for p in _ERROR_PREFIXES) or "status=error" in lowered:
        return FAILED
    return OK if any(m in lowered for m in _OK_MARKERS) else None


def parse_log(text: str) -> RunVerdict:
    """The verdict in this log text; PENDING while no verdict line has arrived."""
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    for line in reversed(lines):        # the verdict is the last thing written
        state = _verdict_of(line)
        if state is not None:
            return RunVerdict(state=state, message=line.strip(), lines=lines)
    return RunVerdict(state=PENDING, message="", lines=lines)


def read_verdict(path: Any) -> RunVerdict:  # type: ignore[valid-type]
    """Read the log file's verdict. A missing file is PENDING, never an error.

    The macro may not have written anything yet — that is the normal first
    state of every run, so it must not look like a failure.
    """
    log_file = Path(str(path or ""))
    try:
        return parse_log(log_file.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError:
        return RunVerdict(state=PENDING, message="", lines=[])
    except OSError as exc:
        return RunVerdict(state=PENDING, message=f"log unreadable: {exc}", lines=[])


def clear_log(path: Any) -> bool:  # type: ignore[valid-type]
    """Delete a stale log before a run so the poller cannot read the last one.

    Returns whether the path is now clear — the caller must not start a run it
    cannot get a fresh verdict for.
    """
    log_file = Path(str(path or ""))
    if not str(path or ""):
        return False
    try:
        log_file.unlink(missing_ok=True)
        return True
    except OSError:
        return False
