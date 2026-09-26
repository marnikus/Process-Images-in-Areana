"""Firefox task window — captcha solve time + stacked Ui.Vision window (owner, 2026-09-26).

1. A security check gets the user's solve time (`captcha_solve_sec`, default
   50 s) with NO macro at all: the lane is quiet (every tab's macros wait
   inside the lock), then ONE check; still there → another window, to the cap.
2. "Stack Ui.Vision window": a job's phases launch with `closeRPA=0`; only
   the task's last macro (the post-task New Chat, or a close macro when New
   Chat is skipped for review evidence) closes the helper window.

The label-macro triggers (feature 3) live in `test_firefox_identity.py`.
"""

import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.browser.uivision import config as uv_config
from app.browser.uivision import job_macros as uv_job
from app.browser.uivision import macro as uv_macro
from app.browser.uivision import sequence as seq_mod
from app.browser.uivision.runner import RunSpec
from app.services import firefox_job as fj
from app.services import firefox_job_phases as ph
from app.services import firefox_lane as fl
from tests.firefox_job_harness import PROMPT, Bridge, baseline, happy_site, run, sent
from tests.test_firefox_lane import CfgBridge, ff_page

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_lane(monkeypatch):
    monkeypatch.setattr(fl, "_QUIET", {})
    monkeypatch.setattr(fl, "_MACRO_LOCK", asyncio.Lock())


def captcha_env(monkeypatch, seconds=0.06):
    monkeypatch.setattr(ph, "solve_seconds", lambda b: seconds)
    monkeypatch.setattr(ph, "SOLVE_STEP_S", 0.01)
    monkeypatch.setattr("app.services.firefox_job_ctx.captcha_in_scope", lambda b: True)
    monkeypatch.setattr(ph, "note_captcha_event", lambda pool, tab, bridge, source: None)


def stacked(bridge, on=True):
    bridge.config.set_state("firefox_auto", {"stack_uivision": on})
    return bridge


# ── 1. captcha solve window ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_solve_window_runs_no_macro_then_checks_once(tmp_path, monkeypatch):
    captcha_env(monkeypatch)
    seen = {}

    def blocked_baseline(token):
        seen["baseline_at"] = time.monotonic()
        return baseline(security=True)

    def check(token):
        seen["check_at"], seen["quiet_at_check"] = time.monotonic(), fl.quiet_left()
        return {"security": {"security": False}}

    site = happy_site(PROMPT, baseline=[blocked_baseline, baseline()], security=check)
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed is False and site.calls.count("security") == 1
    assert seen["check_at"] - seen["baseline_at"] >= 0.06            # the whole window, no macro
    assert site.calls[:3] == ["baseline", "security", "baseline"]    # nothing ran in between
    assert seen["quiet_at_check"] == 0 and fl._QUIET == {}
    assert any("solve it now" in m for b, s, m in bridge.actions if b == "CHECK_SECURITY")


@pytest.mark.asyncio
async def test_still_blocked_opens_another_window_with_a_warning(tmp_path, monkeypatch):
    captcha_env(monkeypatch, seconds=0.02)
    site = happy_site(PROMPT, baseline=[baseline(security=True), baseline()],
                      security=[{"security": {"security": True}}, {"security": {"security": False}}])
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed is False and site.calls.count("security") == 2
    assert any("another" in m and level == "warn" for level, m in bridge.logs)


@pytest.mark.asyncio
async def test_the_lane_is_quiet_for_every_tab_during_the_window(tmp_path, monkeypatch):
    captcha_env(monkeypatch, seconds=0.08)
    quiet_seen = []

    def blocked_baseline(token):
        loop = asyncio.get_running_loop()
        loop.call_later(0.03, lambda: quiet_seen.append(fl.quiet_left()))
        return baseline(security=True)

    site = happy_site(PROMPT, baseline=[blocked_baseline, baseline()],
                      security={"security": {"security": False}})
    await run(tmp_path, site, monkeypatch)
    assert quiet_seen and quiet_seen[0] > 0                          # other tabs would wait


@pytest.mark.asyncio
async def test_cancel_inside_the_window_ends_it_without_a_check(tmp_path, monkeypatch):
    captcha_env(monkeypatch, seconds=5)
    bridge = Bridge(tmp_path / "cfg")

    def blocked_then_cancel(token):
        asyncio.get_running_loop().call_later(0.03, setattr, bridge, "_cancel_requested", True)
        return baseline(security=True)

    site = happy_site(PROMPT, baseline=blocked_then_cancel)
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch, bridge=bridge)
    assert verdict.err == "Cancelled" and "security" not in site.calls and fl._QUIET == {}


def test_solve_seconds_is_the_windows_setting_default_50(tmp_path):
    bridge = Bridge(tmp_path)
    assert ph.solve_seconds(bridge) == 50
    bridge.config.set_state("firefox_auto", {"captcha_solve_sec": 90})
    assert ph.solve_seconds(bridge) == 90


@pytest.mark.parametrize("raw,expected", [(None, 50), (3, 10), (9999, 600), ("x", 50), (75, 75)])
def test_captcha_solve_sec_is_clamped(raw, expected):
    assert uv_config.validate_config({"captcha_solve_sec": raw})["captcha_solve_sec"] == expected


# ── the lane's quiet gate ────────────────────────────────────────────────────

def test_quiet_windows_are_per_owner():
    fl.hold_quiet("a", 30)
    fl.hold_quiet("b", 60)
    assert 55 < fl.quiet_left() <= 60
    fl.end_quiet("b")
    assert 25 < fl.quiet_left() <= 30
    fl.end_quiet("a")
    fl.end_quiet("missing")                                           # tolerated
    assert fl.quiet_left() == 0


@pytest.mark.asyncio
async def test_a_macro_waits_inside_the_lock_until_the_window_ends(monkeypatch):
    started = []

    class FakeSequence:
        def __init__(self, spec, seams, recorder):
            self.page = ""

        async def execute(self, runs):
            started.append(time.monotonic())
            return SimpleNamespace(kind="ok", message="done", lines=())

    monkeypatch.setattr(fl, "Sequence", FakeSequence)
    monkeypatch.setattr(fl, "_fresh", lambda run: run)
    fl.hold_quiet("job", 0.05)
    t0 = time.monotonic()
    assert await fl._run_locked(None, None, lambda spec: "page") == ("ok", "done", ())
    assert started[0] - t0 >= 0.04


# ── 2. stacked Ui.Vision window ──────────────────────────────────────────────

def lane_spec(monkeypatch, tmp_path, phase, stack):
    captured = {}

    async def fake_locked(spec, run, provision):
        captured["spec"] = spec
        return "ok", "done", ()

    monkeypatch.setattr(fl, "_run_locked", fake_locked)
    bridge = CfgBridge(cfg={"storage": "xfile", "stack_uivision": stack})
    bridge.config.dir = str(tmp_path)
    asyncio.run(fl.run_phase(bridge, ff_page(), phase, "c1"))
    return captured["spec"]


@pytest.mark.parametrize("stack,last,closes", [(False, False, True), (False, True, True),
                                               (True, False, False), (True, True, True)])
def test_close_rpa_per_phase(monkeypatch, tmp_path, stack, last, closes):
    phase = replace(uv_job.probe_macro("c1", "baseline", "1"), last=last)
    assert lane_spec(monkeypatch, tmp_path, phase, stack).close_rpa is closes


def test_stack_uivision_defaults_off_and_is_a_bool():
    assert uv_config.validate_config({})["stack_uivision"] is False
    assert uv_config.validate_config({"stack_uivision": 1})["stack_uivision"] is True
    assert RunSpec.__dataclass_fields__["close_rpa"].default is True


@pytest.mark.parametrize("close_rpa,flag", [(True, "1"), (False, "0")])
def test_the_launch_url_carries_close_rpa(monkeypatch, tmp_path, close_rpa, flag):
    monkeypatch.setattr(seq_mod.launch, "resolve_binary", lambda binary: "/fake/firefox")
    monkeypatch.setattr(seq_mod.launch, "binary_exists", lambda binary: True)
    argv_seen = []
    monkeypatch.setattr(seq_mod.launch, "launch_resilient",
                        lambda argv, popen=None: argv_seen.append(argv) or SimpleNamespace(pid=1))
    spec = RunSpec(pattern="", target="css=.x", macro="M", storage="xfile", home="", binary="",
                   timeout_sec=30, pause_ms=500, config_dir=str(tmp_path), close_rpa=close_rpa)
    run = SimpleNamespace(log_path=str(tmp_path / "log.txt"), selector="title=*A*",
                          profile_args=(), index=1, total=1, label="P")
    seq_mod.Sequence(spec, SimpleNamespace(popen=None), lambda *a, **k: None)._launch(run)
    url = next(arg for arg in argv_seen[0] if "closeRPA" in arg)
    query = urlsplit(url).query or urlsplit(url).fragment
    assert parse_qs(query)["closeRPA"] == [flag]


@pytest.mark.asyncio
async def test_the_post_task_new_chat_is_the_last_macro(tmp_path, monkeypatch):
    site = happy_site(PROMPT)
    _, _, _, resets = await run(tmp_path, site, monkeypatch)
    assert not any(p.last for p in site.phases)                      # every job phase keeps it
    await resets[0]()
    assert site.phases[-1].phase == "reset" and site.phases[-1].last is True


@pytest.mark.asyncio
async def test_the_mid_job_stale_composer_reset_keeps_the_window(tmp_path, monkeypatch):
    stale = baseline(previews=[{"alt": "old.png", "blob": True}])
    site = happy_site(PROMPT, baseline=[stale, baseline()])
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    resets = [p for p in site.phases if p.phase == "reset"]
    assert verdict.failed is False and len(resets) == 1 and resets[0].last is False


async def _review_evidence_run(tmp_path, monkeypatch, stack):
    bridge = stacked(Bridge(tmp_path / "cfg"), stack)

    def submit_then_cancel(token):
        bridge._cancel_requested = True
        return sent()

    site = happy_site(PROMPT, submit=submit_then_cancel, close={})
    _, _, _, resets = await run(tmp_path, site, monkeypatch, bridge=bridge)
    assert await resets[0]() == (True, "skipped (needs review)")
    return site, bridge


@pytest.mark.asyncio
async def test_skipped_new_chat_still_closes_a_stacked_window(tmp_path, monkeypatch):
    site, _ = await _review_evidence_run(tmp_path, monkeypatch, stack=True)
    assert site.calls[-1] == "close" and site.phases[-1].last is True and "reset" not in site.calls


@pytest.mark.asyncio
async def test_skipped_new_chat_without_stacking_runs_no_close_macro(tmp_path, monkeypatch):
    site, _ = await _review_evidence_run(tmp_path, monkeypatch, stack=False)
    assert "close" not in site.calls


@pytest.mark.asyncio
async def test_a_failing_close_is_only_a_warning(tmp_path, monkeypatch):
    bridge = stacked(Bridge(tmp_path / "cfg"))

    async def broken(*args):
        raise OSError("firefox gone")

    monkeypatch.setattr(fl, "run_phase", broken)
    job = SimpleNamespace(bridge=bridge, page=None, corr="c1", tab_id="t", img=None)
    monkeypatch.setattr(fj, "log", lambda j, message, level="info": bridge.logs.append((level, message)))
    await fj.close_helper(job)
    assert bridge.logs == [("warn", "Ui.Vision window close failed: firefox gone")]


def test_close_macro_does_no_page_work_and_is_last():
    phase = uv_job.close_macro()
    assert (phase.phase, phase.last, phase.name) == ("close", True, "Arena_Job_Close")
    assert [c["Command"] for c in phase.commands] == ["echo"]
    uv_macro.refuse_dom_clicks(list(phase.commands))
