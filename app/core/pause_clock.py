"""PauseClock — the seconds one generation wait spent inside a captcha wait (S3, D-13/D-14R).

One clock per generation wait. The browser layer charges it around the
security settler (`cdp_arena/output._settle_timed`), the wait loop reads it
(`output_wait._check_timeout` via `paused_elapsed`), and the timeout text
quotes it (`describe`). The cap is cumulative for the whole wait (R22): a
second captcha in the same generation absorbs only what the first one left.
`cap_s <= 0` means uncapped. It lives in `app/core` because both chargers
(browser, services) may import it (D-25). No lock: one wait, one coroutine.
"""

from __future__ import annotations

import math
import time


def _finite_positive(value) -> float:
    """Seconds worth charging: garbage, NaN, inf and non-positive values are 0."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return seconds if math.isfinite(seconds) and seconds > 0 else 0.0


class PauseClock:
    """Absorbed captcha-wait seconds, capped; read by the generation timeout."""

    def __init__(self, cap_s: float = 0.0):
        self.cap_s = max(0.0, _finite_positive(cap_s))
        self.total = 0.0

    def note(self, seconds) -> None:
        """Absorb `seconds`, never more than the cap still allows."""
        charge = _finite_positive(seconds)
        if self.cap_s > 0:
            charge = min(charge, self.remaining())
        self.total += charge

    def expired(self) -> bool:
        """The whole budget is spent (never true for an uncapped clock)."""
        return self.cap_s > 0 and self.total >= self.cap_s

    def remaining(self) -> float:
        """Budget left; infinite when uncapped, never negative."""
        if self.cap_s <= 0:
            return math.inf
        return max(0.0, self.cap_s - self.total)

    def paused_elapsed(self, start: float, now: float | None = None) -> float:
        """Wall seconds since `start` minus what was absorbed — the timeout's clock."""
        now = time.monotonic() if now is None else now
        return max(0.0, (now - start) - self.total)

    def describe(self) -> str:
        """Post-mortem wording: `+12s captcha wait (cap 300s, 288s left)`; empty when unused."""
        if self.total <= 0:
            return ""
        if self.cap_s <= 0:
            return f"+{self.total:.0f}s captcha wait"
        return f"+{self.total:.0f}s captcha wait (cap {self.cap_s:.0f}s, {self.remaining():.0f}s left)"
