"""Per-generation-wait pause budget (S3, D-25).

Lives in core because `output_wait.py` (`max_class_loc` 4) cannot grow a class
and core is the only layer both the browser charger and the wait loop import.
One wait owns one clock; the clock never raises and holds no lock.
"""

from __future__ import annotations

import time


class PauseClock:
    """Absorbed captcha-wait seconds, capped per wait (D-14R, R22)."""

    def __init__(self, cap_s: float = 0.0) -> None:
        """A pause budget; 0 = uncapped (never expires)."""
        try:
            self.cap_s = float(cap_s)
        except Exception:
            self.cap_s = 0.0
        self.total = 0.0

    def note(self, seconds: float) -> None:
        """Absorb seconds into total, never beyond the cap; garbage is ignored."""
        try:
            ok = seconds > 0
        except Exception:
            return
        if not ok:
            return
        charged = self.total + seconds
        self.total = min(charged, self.cap_s) if self.cap_s > 0 else charged

    def expired(self) -> bool:
        """True once the cap is absorbed (uncapped never expires)."""
        return self.cap_s > 0 and self.total >= self.cap_s

    def remaining(self) -> float:
        """Budget left (+inf when uncapped); never negative."""
        return max(0.0, self.cap_s - self.total) if self.cap_s > 0 else float("inf")

    def paused_elapsed(self, start: float, now: float | None = None) -> float:
        """Wall time minus absorbed pause, floored at zero."""
        end = time.monotonic() if now is None else now
        return max(0.0, end - start - self.total)

    def describe(self) -> str:
        """'+12s captcha wait (cap 300s, 288s left)'; '' when nothing absorbed."""
        if self.total <= 0:
            return ""
        return f"+{self.total:g}s captcha wait (cap {self.cap_s:g}s, {self.remaining():g}s left)"
