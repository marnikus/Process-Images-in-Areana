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
async def test_spinner_loss_fires_without_any_settle(monkeypatch):
    """The 12:08 run: spinner seen, then lost, nothing arrives — revive."""
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, reports = arm(ctrl, clock, monkeypatch)
    await maybe_resume(ctrl, dead_diag(spinning=True))  # generation starts
    assert policy.spinner_seen
    for _ in range(6):  # 30 s of dead polls, no settle ever stamped
        clock.t += 5
        await maybe_resume(ctrl, dead_diag())
    assert ctrl.calls == [("insert", PROMPT), ("submit",)]
    assert any("spinner lost" in m for m, _ in reports)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_spinner_flicker_rearms_dead_window(monkeypatch):
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, _ = arm(ctrl, clock, monkeypatch)
    await maybe_resume(ctrl, dead_diag(spinning=True))
    for _ in range(3):  # 15 s dead — inside the window
        clock.t += 5
        await maybe_resume(ctrl, dead_diag())
    assert policy.dead_since is not None and ctrl.calls == []
    await maybe_resume(ctrl, dead_diag(spinning=True))  # flicker back
    assert policy.dead_since is None
    for _ in range(6):  # fresh window must fully mature before firing
        clock.t += 5
        await maybe_resume(ctrl, dead_diag())
    assert [c[0] for c in ctrl.calls] == ["insert", "submit"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_settle_then_resume_then_die_fires_via_loss(monkeypatch):
    """Resumed generation stands the settle trigger down; later loss revives."""
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, reports = arm(ctrl, clock, monkeypatch)
    note_settle(ctrl)
    await maybe_resume(ctrl, dead_diag(spinning=True))  # resumed, not dead
    assert policy.settled_at is None and ctrl.calls == []
    for _ in range(6):  # then it dies for real — loss trigger matures
        clock.t += 5
        await maybe_resume(ctrl, dead_diag())
    assert [c[0] for c in ctrl.calls] == ["insert", "submit"]
    assert any("spinner lost" in m for m, _ in reports)


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


class AttachCtrl(FakeCtrl):
    """FakeCtrl + attachment + send-ready surface (CDP controller shape)."""

    def __init__(self, attached=True, attach_fail=False, **kw):
        super().__init__(**kw)
        self._attached = attached
        self._attach_fail = attach_fail

    async def verify_attachment(self, expected_filename):
        self.calls.append(("verify", expected_filename))
        return self._attached, "Found via blob" if self._attached else "Not found"

    async def attach_image(self, image_path):
        if self._attach_fail:
            raise RuntimeError("file input gone")
        self.calls.append(("attach", image_path))
        return True, "Attached"

    async def submit_when_ready(self, timeout_sec=8.0):
        self.calls.append(("submit_ready",))
        return self._submit_ok, "Clicked"


async def fire(ctrl, clock, monkeypatch, image_path=None):
    """Arm, settle, mature the grace window, run one dead poll."""
    policy, reports = arm(ctrl, clock, monkeypatch)
    if image_path:
        policy.image_path = image_path
    note_settle(ctrl)
    clock.t += RESUME_GRACE_SEC + 1
    await maybe_resume(ctrl, dead_diag())
    return policy, reports


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resubmit_prefers_submit_when_ready(monkeypatch):
    ctrl, clock = AttachCtrl(), FakeClock()
    await fire(ctrl, clock, monkeypatch)
    assert [c[0] for c in ctrl.calls] == ["insert", "submit_ready"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resubmit_reattaches_when_attachment_missing(monkeypatch):
    ctrl, clock = AttachCtrl(attached=False), FakeClock()
    await fire(ctrl, clock, monkeypatch, image_path="/tmp/pic/img1.png")
    assert ctrl.calls[0] == ("verify", "img1.png")
    assert ctrl.calls[1] == ("attach", "/tmp/pic/img1.png")
    assert [c[0] for c in ctrl.calls[2:]] == ["insert", "submit_ready"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resubmit_skips_attach_when_present(monkeypatch):
    ctrl, clock = AttachCtrl(attached=True), FakeClock()
    await fire(ctrl, clock, monkeypatch, image_path="/tmp/pic/img1.png")
    assert [c[0] for c in ctrl.calls] == ["verify", "insert", "submit_ready"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resubmit_without_image_path_skips_attach(monkeypatch):
    ctrl, clock = AttachCtrl(attached=False), FakeClock()
    await fire(ctrl, clock, monkeypatch)  # no image_path armed
    assert [c[0] for c in ctrl.calls] == ["insert", "submit_ready"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resubmit_attach_failure_still_sends(monkeypatch):
    ctrl, clock = AttachCtrl(attached=False, attach_fail=True), FakeClock()
    _, reports = await fire(ctrl, clock, monkeypatch, image_path="/tmp/pic/img1.png")
    assert [c[0] for c in ctrl.calls] == ["verify", "insert", "submit_ready"]
    assert any("re-attach failed" in m for m, _ in reports)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dead_generation_toast_fires_immediately(monkeypatch):
    """The site's 'Please try again.' toast is authoritative death proof —
    revival fires on the SAME poll, no grace window, no settle needed."""
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, reports = arm(ctrl, clock, monkeypatch)
    diag = dead_diag(dead_generation_error="Page error: Something went wrong while generating the response. Please try again.")
    assert await maybe_resume(ctrl, diag) is diag
    assert ctrl.calls == [("insert", PROMPT), ("submit",)]  # resubmitted once
    assert policy.resubmits == 1
    assert any("retrying as the page instructs" in m for m, _ in reports)
    await maybe_resume(ctrl, dead_diag(dead_generation_error="again"))
    assert len(ctrl.calls) == 2  # budget stays ONE per wait


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dead_generation_marker_cleared_by_live_request(monkeypatch):
    """A spinning/new-output poll stands the death proof down (no zombie fire)."""
    ctrl, clock = FakeCtrl(), FakeClock()
    policy, _ = arm(ctrl, clock, monkeypatch)
    policy.max_resubmits = 0  # observe markers only, never resubmit
    await maybe_resume(ctrl, dead_diag(dead_generation_error="Page error: Something went wrong while generating"))
    assert policy.gen_error  # death proof recorded (no resubmit: zero budget)
    await maybe_resume(ctrl, dead_diag(spinning=True))
    assert policy.gen_error == "" and policy.dead_since is None
