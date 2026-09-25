"""The lane seam the image job runs through (steps 14/15, design §5).

`run_job_stage` is `run_identify`'s twin: same machine-wide lock, same
user-defined inter-run delay, same provisioning and savelog poll — only the
macro (a per-job stage document), the locator (the pool entry's own tab) and the
in-page budget differ. `reset_page` is the New-chat step: the macro clicks the
link natively and the *page* has to prove the clean state.

The job's own stage machine is tested in `test_firefox_job_flow.py`; here the
scripted savelog verdict is the answer under test.

RED at base: neither function existed in `app/services/firefox_lane.py`.
"""

from __future__ import annotations

import asyncio

import pytest

from app.browser.uivision import job_macro as jm
from app.browser.uivision.pool_tabs import FirefoxPageInfo
from app.services import firefox_lane as fl

pytestmark = pytest.mark.unit


class CfgBridge:
    def __init__(self, cfg=None, cancel=False):
        stored = {"firefox_auto": dict(cfg or {"storage": "xfile", "home": "/tmp/uiv",
                                               "inter_run_delay_sec": 0})}
        self.config = type("C", (), {
            "dir": "/tmp/cfg",
            "get_state": staticmethod(lambda key, default=None: stored.get(key, default)),
        })()
        self._cancel_requested = cancel
        self.logs = []

    def _log(self, message, level="info"):
        self.logs.append((level, message))


def ff_page(url="https://arena.ai/c/7", title="Arena chat"):
    return FirefoxPageInfo(ws_url="", tab_id="9THrgpBc.Profile1_tab1", url=url,
                           title=title, browser="firefox", is_connected=True,
                           profile="P1", profile_dir="/x/9THrgpBc.Profile1")


def inputs(stage="prepare", **kw):
    base = dict(stage=stage, token="20260925-142530-A7F3", image_path="/tmp/a.png",
                file_name="a.png", prompt="p", budget_ms=jm.budget_for(stage))
    base.update(kw)
    return jm.StageInputs(**base)


class FakeSequence:
    """A fake `Sequence`: records what the lane asked for and answers a canned savelog."""

    seen = []
    answer = ("ok", "stage done", ())

    def __init__(self, spec, seams, report):
        self.spec, self.page, self.seams, self.report = spec, "", seams, report

    async def execute(self, runs):
        from app.browser.uivision.sequence import RunResult
        FakeSequence.seen.append((self.spec, runs[0], self.page, fl._MACRO_LOCK.locked()))
        self.report("stage", f"{self.spec.macro} → {runs[0].selector}", "info")
        kind, message, lines = FakeSequence.answer
        return RunResult(kind=kind, message=message, lines=tuple(lines))


@pytest.fixture
def lane(monkeypatch):
    """The lane with its expensive seams replaced (no Firefox, no macro files)."""
    FakeSequence.seen = []
    FakeSequence.answer = ("ok", "stage done", ())
    written = []
    monkeypatch.setattr(fl, "Sequence", FakeSequence)
    monkeypatch.setattr(fl, "_wait_gap", _no_gap)
    monkeypatch.setattr(fl, "_LAST_AT", 0.0)
    monkeypatch.setattr(fl, "_MACRO_LOCK", asyncio.Lock())
    monkeypatch.setattr(fl.uv_job_macro, "write_stage",
                        lambda spec, inputs: written.append((spec.macro, inputs.stage)))
    monkeypatch.setattr(fl.uv_job_macro, "page", lambda spec: "/tmp/autorun.html")
    return FakeSequence, written


async def _no_gap(_cfg):
    return None


@pytest.mark.asyncio
async def test_a_stage_runs_as_its_own_macro_with_its_own_budget(lane):
    fake, written = lane
    kind, message, lines = await fl.run_job_stage(CfgBridge(), ff_page(), inputs("submit", budget_ms=240000))
    assert (kind, message) == ("ok", "stage done")
    spec, run, page, locked = fake.seen[0]
    assert spec.macro == "Arena_Job_Submit_20260925-142530-A7F3"
    assert spec.pause_ms == 240000                      # the stage budget rides cmd_var1
    assert spec.pattern == "" and spec.url_pattern == "https://arena.ai/c/7"
    assert run.selector == "title=*Arena chat*"         # the tab's own title as the fallback
    assert "submit-" in run.log_path                    # one savelog per stage, never shared
    assert page == "/tmp/autorun.html" and locked is True
    assert written == [(spec.macro, "submit")]          # the stage macro file was written
    assert lines == ()


@pytest.mark.asyncio
async def test_a_stage_answers_the_savelog_lines_the_job_parses(lane):
    fake, _written = lane
    fake.answer = ("ok", "done", ("Status=OK", 'echo: ARENA_STATE={"clean":true}', "###"))
    _kind, _message, lines = await fl.run_job_stage(CfgBridge(), ff_page(), inputs("probe"))
    assert any("ARENA_STATE=" in line for line in lines)      # job_replies parses anywhere


@pytest.mark.asyncio
async def test_browser_storage_answers_blocked_instead_of_running_a_stale_macro(lane):
    """The browser store cannot receive a written macro — the job must not run one."""
    fake, written = lane
    bridge = CfgBridge({"storage": "browser", "home": "/tmp/uiv", "inter_run_delay_sec": 0})
    kind, message, lines = await fl.run_job_stage(bridge, ff_page(), inputs("prepare"))
    assert kind == "blocked" and "hard-drive" in message
    assert fake.seen == [] and written == []


@pytest.mark.asyncio
async def test_cancel_before_the_launch_runs_nothing(lane):
    fake, written = lane
    kind, message, _lines = await fl.run_job_stage(CfgBridge(cancel=True), ff_page(), inputs("prepare"))
    assert kind == "stopped" and "cancelled" in message
    assert fake.seen == [] and written == []


@pytest.mark.asyncio
async def test_every_stage_reports_through_the_job_reporter(lane):
    fake, _written = lane
    seen = []

    def report(step, message, level="info"):
        seen.append((level, step, message))

    await fl.run_job_stage(CfgBridge(), ff_page(), inputs("fetch"), report=report)
    assert seen and seen[0][1] == "stage" and "Arena_Job_Fetch" in seen[0][2]
    assert fake.seen and "fetch-" in fake.seen[0][1].log_path


@pytest.mark.asyncio
async def test_one_stage_at_a_time_even_when_two_jobs_dispatch_together(lane, monkeypatch):
    """The machine-wide lock: two stages of two jobs never overlap in the extension."""
    fake, _written = lane
    active = {"now": 0, "peak": 0}

    async def slow_execute(self, runs):
        from app.browser.uivision.sequence import RunResult
        active["now"] += 1
        active["peak"] = max(active["peak"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return RunResult(kind="ok", message="done", lines=())

    monkeypatch.setattr(fake, "execute", slow_execute)
    await asyncio.gather(fl.run_job_stage(CfgBridge(), ff_page(), inputs("prepare")),
                         fl.run_job_stage(CfgBridge(), ff_page(), inputs("submit")))
    assert active["peak"] == 1


@pytest.mark.asyncio
async def test_a_clean_page_verdict_comes_from_the_pages_own_answer(lane):
    fake, written = lane
    fake.answer = ("ok", "done",
                   ('echo: ARENA_STATE={"clean":true,"textarea":true,"composer":{"len":0}}',))
    clean, reason = await fl.reset_page(CfgBridge(), ff_page())
    assert clean is True and "composer empty" in reason
    assert written == [("Arena_Job_Newchat_reset", "newchat")]   # the reset's own macro


@pytest.mark.asyncio
async def test_a_dirty_or_silent_page_is_not_clean(lane):
    fake, _written = lane
    fake.answer = ("ok", "done", ('echo: ARENA_STATE={"clean":false,"textarea":true,'
                                  '"previews":[{"alt":"a.png"}]}',))
    clean, reason = await fl.reset_page(CfgBridge(), ff_page())
    assert clean is False and "attachment(s) still" in reason
    fake.answer = ("ok", "done", ())
    clean, reason = await fl.reset_page(CfgBridge(), ff_page())
    assert clean is False and "no page state answer" in reason
