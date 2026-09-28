"""The cooling countdown is logged per minute, at most twice in the last minute (2026-09-28).

Owner: "the log contains the cooldown countdown every few seconds — spam; only every
1 min, and 2 in the last minute maximum". Before: one line every 10 s (~30 per 5 min).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.cooldown import countdown_mark
from app.services import cooldown_service as svc


@pytest.mark.parametrize("left, mark", [
    (300, 5), (241, 5), (240, 4), (121, 3), (120, 2), (61, 2),
    (60, 1), (31, 1), (30, 0.5), (1, 0.5), (0, 0.5), (-5, 0.5),
])
def test_marks_are_whole_minutes_then_one_minute_and_thirty_seconds(left, mark):
    assert countdown_mark(left) == mark


class _ScriptedPage:
    """A cooling page whose remaining seconds follow a script (one value per check)."""

    def __init__(self, script):
        self._script = iter(script)
        self.left = None

    def is_free(self):
        return False

    def remaining_seconds(self):
        if self.left is None:
            self.left = next(self._script)
        return self.left


def _wait_log(monkeypatch, script):
    """Run the single-page wait over `script` (a check every 2 s); return its log lines."""
    page = _ScriptedPage([])
    values = iter(script)

    def get_page(tab_id):
        page.left = next(values)
        return page
    pool = SimpleNamespace(get_page=get_page, _host="", _port=0)
    logs = []
    bridge = SimpleNamespace(_cancel_requested=False, _pause_requested=False,
                             _log=lambda m, l="info": logs.append(m))
    monkeypatch.setattr(svc, "_POLL_SEC", 0)
    monkeypatch.setattr(svc, "refresh_expired", lambda pool: None)
    monkeypatch.setattr(svc, "_label", lambda pool, tab_id: "user_0001")
    import asyncio
    assert asyncio.run(svc.wait_for_tab_ready(pool, "t", bridge)) is True
    return [m for m in logs if "cooling" in m]


def test_a_five_minute_wait_logs_six_lines_not_thirty(monkeypatch):
    lines = _wait_log(monkeypatch, list(range(300, -1, -2)))
    assert [line.split("cooling ")[1][:5] for line in lines] == ["05:00", "04:00", "03:00", "02:00", "01:00", "00:30"]


def test_the_last_minute_has_at_most_two_lines(monkeypatch):
    lines = _wait_log(monkeypatch, list(range(58, -1, -2)))
    assert [line.split("cooling ")[1][:5] for line in lines] == ["00:58", "00:30"]   # joined in the last minute
    lines = _wait_log(monkeypatch, list(range(90, -1, -1)))
    assert sum(1 for line in lines if line.split("cooling ")[1] < "01:01") <= 2


def test_a_wait_that_starts_mid_minute_logs_once_then_on_the_minutes(monkeypatch):
    lines = _wait_log(monkeypatch, list(range(157, -1, -2)) + [0])
    # checks every 2 s from an odd second: each line is the first check past the minute, true time shown
    assert [line.split("cooling ")[1][:5] for line in lines] == ["02:37", "01:59", "00:59", "00:29"]
