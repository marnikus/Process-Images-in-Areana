"""PauseClock — how much of a generation wait a captcha pause absorbed (S3).

D-25/D-13/D-14R: one clock per generation wait. The browser layer charges
every second spent inside the captcha settle (`note`), the wait loop
subtracts it (`paused_elapsed`), and the cap bounds both how much one wait
may absorb and how long the wait itself may last (the deadline side lives
in `captcha.policy.WaitDeadline`). Pure value object: no Qt, no bridge,
no locks (one wait, one coroutine), never raises.
"""

import math
import time


class PauseClock:
    """Cumulative pause seconds with an optional cap (`cap_s <= 0` = uncapped)."""

    def __init__(self, cap_s: float = 0.0):
        self.cap_s = float(cap_s)
        self.total = 0.0

    def note(self, seconds: float) -> None:
        """Charge pause time; garbage (<= 0, NaN) is ignored (never raises)."""
        try:
            s = float(seconds)
        except (TypeError, ValueError):
            return
        if not math.isfinite(s) or s <= 0:
            return
        if self.cap_s > 0:
            s = min(s, self.cap_s - self.total)  # R22: the cap is cumulative
            if s <= 0:
                return
        self.total += s

    def expired(self) -> bool:
        return self.cap_s > 0 and self.total >= self.cap_s

    def remaining(self) -> float:
        if self.cap_s <= 0:
            return float("inf")
        return max(0.0, self.cap_s - self.total)

    def paused_elapsed(self, start: float, now: float | None = None) -> float:
        """Wall time since `start` minus absorbed pause, floored at zero."""
        wall = (time.monotonic() if now is None else now) - start
        return max(0.0, wall - self.total)

    def describe(self) -> str:
        if self.total <= 0:
            return ""
        if self.cap_s <= 0:
            return f"+{self.total:.0f}s captcha wait (uncapped)"
        return (f"+{self.total:.0f}s captcha wait "
                f"(cap {self.cap_s:.0f}s, {self.remaining():.0f}s left)")
