"""A cooldown wait logs at most TWO lines: 60 s into the wait, and 30 s before its end (2026-09-28).

Owner, round 1: "the log repeats the countdown every few sec — spam" (was every 10 s).
Owner, round 2: "too many — reduce to 2 msg max: the first minute of elapsing and the
last minute before the wait ends". Round 3: "leave only 04:00 and then 00:30" (a 5-minute
pause). Both waiting loggers follow `CountdownNotes` / `countdown_note`:
the single-tab wait (`wait_for_tab_ready`) and the live run's "all tabs cooling" line.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.cooldown import CountdownNotes, countdown_note
from app.services import cooldown_service as svc
from app.services.live import supervisor as sv
from app.services.live.bus import LiveBus


@pytest.mark.parametrize("start, left, note", [
    (300, 300, ""), (300, 241, ""), (300, 240, "first minute"), (300, 31, "first minute"),
    (300, 30, "last 30 s"), (58, 40, ""), (58, 30, "last 30 s"), (20, 20, "last 30 s"),
])
def test_notes_fall_due_sixty_seconds_in_and_thirty_seconds_before_the_end(start, left, note):
    assert countdown_note(start, left) == note


def test_each_note_is_due_once():
    notes = CountdownNotes()
    assert [notes.due(left) for left in (300, 240, 238, 30, 28, 0)] == ["", "first minute", "", "last 30 s", "", ""]


# ── the single-tab wait ─────────────────────────────────────────────────────

class _Page:
    left = 0

    def is_free(self):
        return False

    def remaining_seconds(self):
        return self.left


def _tab_wait_lines(monkeypatch, script):
    """Run `wait_for_tab_ready` over `script` (seconds left at each check); its cooling lines."""
    page, values = _Page(), iter(script)

    def get_page(tab_id):
        page.left = next(values)
        return page
    logs = []
    bridge = SimpleNamespace(_cancel_requested=False, _pause_requested=False,
                             _log=lambda m, l="info": logs.append(m))
    monkeypatch.setattr(svc, "_POLL_SEC", 0)
    monkeypatch.setattr(svc, "refresh_expired", lambda pool: None)
    monkeypatch.setattr(svc, "_label", lambda pool, tab_id: "user_0001")
    assert asyncio.run(svc.wait_for_tab_ready(SimpleNamespace(get_page=get_page), "t", bridge)) is True
    return [m.split("cooling ")[1][:5] for m in logs if "cooling" in m]


def test_a_five_minute_wait_logs_only_04_00_and_00_30(monkeypatch):
    assert _tab_wait_lines(monkeypatch, list(range(300, -1, -2))) == ["04:00", "00:30"]


def test_a_fifteen_minute_captcha_penalty_still_logs_two_lines(monkeypatch):
    assert _tab_wait_lines(monkeypatch, list(range(900, -1, -2))) == ["14:00", "00:30"]


def test_a_wait_that_starts_in_the_last_minute_logs_only_00_30(monkeypatch):
    assert _tab_wait_lines(monkeypatch, list(range(58, -1, -2))) == ["00:30"]


def test_a_very_short_wait_logs_one_line_when_it_starts(monkeypatch):
    assert _tab_wait_lines(monkeypatch, list(range(20, -1, -2))) == ["00:20"]


def test_a_wait_that_starts_mid_minute_logs_the_true_time_left_at_each_note(monkeypatch):
    assert _tab_wait_lines(monkeypatch, list(range(157, -1, -2)) + [0]) == ["01:37", "00:29"]


# ── the live run's "all tabs cooling" line ──────────────────────────────────

def _supervisor_lines(monkeypatch, script, step_s=2.0):
    """Call `wait_reason` once per value of `script` (soonest tab's seconds left), a fake
    clock advancing `step_s` per call — long waits cross the 5-minute throttle window."""
    now = [0.0]
    bus = LiveBus(clock=lambda: now[0])
    snapshot = {"pages": [{"tab_id": "t1", "cooldown_remaining": 0}]}
    logs = []
    bridge = SimpleNamespace(_page_pool=SimpleNamespace(status_snapshot=lambda: snapshot),
                             _log=lambda m, l="info": logs.append(m))
    monkeypatch.setattr(sv, "WAIT_S", 0)
    monkeypatch.setattr(sv, "pool_summary", lambda pool: "1 page")
    plan = sv.PassPlan(allowed={"t1"}, reason="all cooling")

    async def run():
        for left in script:
            snapshot["pages"][0]["cooldown_remaining"] = left
            await sv.wait_reason(bridge, plan, bus)
            now[0] += step_s
    asyncio.run(run())
    return [m.split("next ready in ")[1][:5] for m in logs if "All tabs cooling" in m], bridge


def test_all_tabs_cooling_for_fifteen_minutes_logs_two_lines(monkeypatch):
    lines, bridge = _supervisor_lines(monkeypatch, list(range(900, 0, -2)))
    assert lines == ["14:00", "00:30"]                       # was one more line every 5 minutes
    assert bridge._live_reason == "all cooling"              # the run badge still reads the plain reason


def test_all_tabs_cooling_inside_the_last_minute_logs_only_00_30(monkeypatch):
    lines, _ = _supervisor_lines(monkeypatch, list(range(50, 0, -2)))
    assert lines == ["00:30"]


def test_other_wait_reasons_keep_their_five_minute_reminder(monkeypatch):
    """Only the cooldown countdown changed — 'no tab' still reminds every 5 min."""
    now = [0.0]
    bus = LiveBus(clock=lambda: now[0])
    logs = []
    bridge = SimpleNamespace(_page_pool=None, _log=lambda m, l="info": logs.append(m))
    monkeypatch.setattr(sv, "WAIT_S", 0)
    monkeypatch.setattr(sv, "pool_summary", lambda pool: "0 pages")
    plan = sv.PassPlan(reason="no tab")

    async def run():
        for _ in range(0, 660, 2):
            await sv.wait_reason(bridge, plan, bus)
            now[0] += 2.0
    asyncio.run(run())
    assert sum("No usable checked tab" in m for m in logs) == 3   # 0 s, 300 s, 600 s
