"""PauseClock — seconds a generation wait may not count against its timeout (S3, I-52).

One clock per generation wait. The browser layer charges it (`note`) while a
captcha settle runs inside the wait; the wait loop reads it
(`paused_elapsed`) so the settle does not burn the generation timeout. The
charge is capped per wait: a second settle absorbs only what is left
(R22). `cap_s <= 0` means uncapped (never expires).

Core layer: stdlib only; no lock (one wait, one coroutine); never raises.
"""

from __future__ import annotations

import math
import time


class PauseClock:
    """Absorbed captcha-wait seconds, capped at `cap_s` (0 = uncapped)."""

    def __init__(self, cap_s: float = 0.0):
        self.cap_s = float(cap_s) if cap_s and cap_s > 0 else 0.0
        self.total = 0.0

    def note(self, seconds) -> None:
        """Charge a settle; ignores ≤0 / NaN / garbage; never exceeds `cap − total`."""
        try:
            secs = float(seconds)
        except (TypeError, ValueError):
            return
        if math.isnan(secs) or secs <= 0:
            return
        self.total += min(secs, self.remaining())

    def expired(self) -> bool:
        """True once the cap is used up (an uncapped clock never expires)."""
        return self.cap_s > 0 and self.total >= self.cap_s

    def remaining(self) -> float:
        """Budget left; `inf` when uncapped; never negative."""
        return max(0.0, self.cap_s - self.total) if self.cap_s > 0 else math.inf

    def paused_elapsed(self, start: float, now: float | None = None) -> float:
        """Wall-clock elapsed since `start` minus the absorbed seconds, floored at 0."""
        current = time.monotonic() if now is None else now
        return max(0.0, current - start - self.total)

    def describe(self) -> str:
        """Human evidence for the timeout text; '' when nothing was absorbed."""
        if self.total <= 0:
            return ""
        text = f"+{int(self.total)}s captcha wait"
        if self.cap_s > 0:
            text += f" (cap {int(self.cap_s)}s, {int(self.remaining())}s left)"
        return text
