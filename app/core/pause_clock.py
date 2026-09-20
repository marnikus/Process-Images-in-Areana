"""PauseClock — the per-generation-wait captcha pause accumulator (D-14R).

While the generation wait polls, a captcha settle charges seconds onto this
clock; `_check_timeout` then measures *paused* elapsed time, so the page's
timeout stops burning while a captcha blocks the page — but only up to the
cap (`watcher_captcha_timeout_sec`, ONE knob). A second settle in the same
wait cannot absorb anything past the cap (R22). Watcher OFF installs no clock
at all (D-23): the timeout then runs in pure wall time, unchanged from S2.

Layering: lives in `app/core/` because both chargers (`cdp_arena/output.py`)
and readers (`output_wait.py`) sit below services, and services → core only.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass


@dataclass
class PauseClock:
    """Counts seconds donated to a captcha wait; never more than `cap_s`."""

    cap_s: float = 0.0
    total: float = 0.0

    def note(self, seconds) -> None:
        """Charge a settle's wall time. Garbage in, nothing charged."""
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            return
        if seconds <= 0 or math.isnan(seconds) or math.isinf(seconds):
            return
        if self.cap_s > 0:
            self.total = min(self.cap_s, self.total + seconds)
        else:
            self.total += seconds

    def expired(self) -> bool:
        """True only when a capped clock absorbed its whole budget."""
        return self.cap_s > 0 and self.total >= self.cap_s

    def remaining(self) -> float:
        """Seconds still absorbable; uncapped clocks have no limit."""
        if self.cap_s <= 0:
            return math.inf
        return max(0.0, self.cap_s - self.total)

    def paused_elapsed(self, start: float, now: float | None = None) -> float:
        """Wall elapsed minus the charged pause, floored at zero."""
        end = time.monotonic() if now is None else now
        return max(0.0, (end - start) - self.total)

    def describe(self) -> str:
        """Failure-text vocabulary: how much was absorbed and what remains."""
        if self.total <= 0:
            return ""
        return (f"+{int(self.total)}s captcha wait "
                f"(cap {int(self.cap_s)}s, {int(self.remaining())}s left)")
