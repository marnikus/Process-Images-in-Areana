"""Post-captcha revival — one bounded resubmit when the blocked generation died.

RULE 8: the real recovery policy against a fake ctrl (records insert/submit)
and a controllable clock for the grace window. Each test asserts on the
recorded calls, so a gate that fires wrongly (or never) fails loudly.
"""

import pytest

import app.services.captcha.recovery as recovery_mod
from app.services.captcha.recovery import (
    RESUME_GRACE_SEC,
    arm_resume,
    clear_resume,
    maybe_resume,
    note_settle,
)

PROMPT = "[JOB-ID: abc] a red icon"


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeCtrl:
    """Job-runner ctrl double: records prompt re-insert + Send."""

    def __init__(self, insert_ok=True, submit_ok=True, fail=False):
        self.calls = []
        self._insert_ok = insert_ok
        self._submit_ok = submit_ok
        self._fail = fail

    async def insert_prompt(self, prompt):
        if self._fail:
            raise RuntimeError("cdp down")
        self.calls.append(("insert", prompt))
        return self._insert_ok, "Inserted len 9"

    async def submit(self):
        if self._fail:
            raise RuntimeError("cdp down")
        self.calls.append(("submit",))
        return self._submit_ok, "Clicked"


def dead_diag(**over):
    d = {"ready": False, "reason": "generating_no_new_yet",
         "spinning": False, "allNew": 0}
    d.update(over)
    return d


def arm(ctrl, clock, monkeypatch, **kw):
    monkeypatch.setattr(recovery_mod.time, "monotonic", clock)
    reports = []
    kw.setdefault("report", lambda m, l="info": reports.append((m, l)))
    policy = arm_resume(ctrl, PROMPT, **kw)
    return policy, reports


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_policy_is_noop():
    ctrl = FakeCtrl()
    diag = dead_diag()
    assert await maybe_resume(ctrl, diag) is diag
    assert ctrl.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsettled_policy_never_fires(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    arm(ctrl, clock, monkeypatch)
    clock.t += RESUME_GRACE_SEC + 60
    assert await maybe_resume(ctrl, dead_diag()) is not None
    assert ctrl.calls == []  # no settle stamped → nothing to revive


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ready_diag_never_resubmits(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    arm(ctrl, clock, monkeypatch)
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    diag = dead_diag(ready=True, src="https://x/img.png")
    assert await maybe_resume(ctrl, diag) is diag
    assert ctrl.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pre_grace_never_resubmits(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, _ = arm(ctrl, clock, monkeypatch)
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC - 1  # still inside the grace window
    await maybe_resume(ctrl, dead_diag())
    assert ctrl.calls == []
    assert policy.settled_at is not None  # marker kept for later polls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_spinning_clears_marker(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, _ = arm(ctrl, clock, monkeypatch)
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    await maybe_resume(ctrl, dead_diag(spinning=True))
    assert ctrl.calls == []
    assert policy.settled_at is None  # live generation → stand down


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_pixels_clear_marker(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, _ = arm(ctrl, clock, monkeypatch)
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    await maybe_resume(ctrl, dead_diag(allNew=2))
    assert ctrl.calls == []
    assert policy.settled_at is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dead_past_grace_resubmits_once(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, reports = arm(ctrl, clock, monkeypatch)
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    diag = dead_diag()
    assert await maybe_resume(ctrl, diag) is diag
    assert ctrl.calls == [("insert", PROMPT), ("submit",)]  # re-insert, then Send
    assert policy.resubmits == 1
    assert any("resubmitting once" in m for m, _ in reports)  # loud (RULE 2)
    await maybe_resume(ctrl, dead_diag())  # next poll: budget spent
    assert ctrl.calls == [("insert", PROMPT), ("submit",)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_second_settle_after_fire_does_not_refire(monkeypatch):
    """Budget is per-wait: a second captcha after a resubmit stays manual."""
    ctrl, clock = FakeCtrl(), FakeClock()
    arm(ctrl, clock, monkeypatch, report=None)  # file-log fallback path
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    await maybe_resume(ctrl, dead_diag())
    assert len(ctrl.calls) == 2
    note_settle(ctrl)  # a fresh challenge appears later in the same wait
    clock.t += RESUME_GRACE_SEC + 1
    await maybe_resume(ctrl, dead_diag())
    assert len(ctrl.calls) == 2  # budget spent — no second resubmit


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gate_attribute_protocol_matches_cdp_arena(monkeypatch):
    """cdp_arena calls ctrl.resume_gate(diag) — the armed attribute works."""
    ctrl, clock = FakeCtrl(), FakeClock()
    arm(ctrl, clock, monkeypatch)
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    await ctrl.resume_gate(dead_diag())
    assert [c[0] for c in ctrl.calls] == ["insert", "submit"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancelled_never_resubmits(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    arm(ctrl, clock, monkeypatch, cancelled=lambda: True)
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    await maybe_resume(ctrl, dead_diag())
    assert ctrl.calls == []  # stop honoured (RULE 7)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fail_open_on_ctrl_errors(monkeypatch):
    ctrl, clock = FakeCtrl(fail=True), FakeClock()
    policy, reports = arm(ctrl, clock, monkeypatch)
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    diag = dead_diag()
    assert await maybe_resume(ctrl, diag) is diag  # never raises (RULE 9)
    assert policy.resubmits == 1  # budget consumed even on failure
    assert any("failed" in m for m, _ in reports)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_note_and_clear_without_policy_are_noops(monkeypatch):
    ctrl = FakeCtrl()
    note_settle(ctrl)  # boundary settles with no armed wait: silent
    clear_resume(ctrl)
    assert getattr(ctrl, "_resume_policy", None) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_removes_policy_and_gate(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    arm(ctrl, clock, monkeypatch)
    assert getattr(ctrl, "_resume_policy", None) is not None
    clear_resume(ctrl)
    assert getattr(ctrl, "_resume_policy", None) is None
    assert getattr(ctrl, "resume_gate", None) is None
