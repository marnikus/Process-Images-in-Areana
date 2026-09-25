"""`firefox_lane.run_identify` + the reconcile seam that drives it (2026-09-25).

The identify macro rides the job lane's machinery: the spec from the SAME
validated config, retargeted at `Arena_Identify` with the payload on cmd_var2
and the in-page wait on cmd_var1; its own savelog file; the machine-wide
macro lock (never races a job). Browser storage cannot receive a written
macro, so it answers `blocked` before anything launches (RULE 4). The
reconcile pass hands its rows to `LiveDeps.identify` AFTER membership exits.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.browser.uivision import identify as uv_identify
from app.browser.uivision.sequence import RunResult
from app.services import firefox_lane as fl
from app.services.live import reconcile as rc
from app.ui.panels import browser_tabs
from tests.test_firefox_lane import CfgBridge, ff_page

pytestmark = pytest.mark.unit


class FakeSequence:
    seen = []

    def __init__(self, spec, seams, report):
        self.spec, self.page = spec, ""

    async def execute(self, runs):
        FakeSequence.seen.append((self.spec, runs[0], fl._MACRO_LOCK.locked(), self.page))
        return RunResult(kind="ok", message="macro completed", lines=("[echo] ARENA_IDENTITY={}",))


@pytest.fixture
def lane(monkeypatch, tmp_path):
    FakeSequence.seen = []
    monkeypatch.setattr(fl, "Sequence", FakeSequence)
    monkeypatch.setattr(fl.uv_identify, "provision", lambda spec: "/page.html")
    monkeypatch.setattr(fl.uv_tabs, "profile_sessions", lambda profiles=None: [])
    monkeypatch.setattr(fl, "_LAST_AT", 0.0)
    monkeypatch.setattr(fl, "_MACRO_LOCK", asyncio.Lock())   # a contended lock binds to its loop
    cfg = {"storage": "xfile", "home": str(tmp_path / "uv"), "target": "css=.x"}
    return CfgBridge(cfg)


@pytest.mark.asyncio
async def test_identify_runs_its_own_macro_with_the_payload_under_the_lock(lane):
    payload = uv_identify.payload(2, "Profile1")
    kind, message, lines = await fl.run_identify(lane, ff_page(), payload)
    spec, run, locked, page = FakeSequence.seen[0]
    assert (kind, message) == ("ok", "macro completed") and lines
    assert spec.macro == "Arena_Identify" and json.loads(spec.target)["no"] == 2
    assert spec.pause_ms == uv_identify.WAIT_MS
    assert run.selector == "title=*Arena chat*" and "identify-" in run.log_path
    assert locked is True and page == "/page.html"


@pytest.mark.asyncio
async def test_browser_storage_is_blocked_before_any_launch(lane):
    lane.config.get_state("firefox_auto")["storage"] = "browser"
    kind, message, lines = await fl.run_identify(lane, ff_page(), uv_identify.payload(1, "P"))
    assert kind == "blocked" and "xfile" in message and lines == ()
    assert FakeSequence.seen == []


@pytest.mark.asyncio
async def test_identify_waits_for_a_running_job_macro(lane):
    async with fl._MACRO_LOCK:
        task = asyncio.ensure_future(fl.run_identify(lane, ff_page(), uv_identify.payload(1, "P")))
        await asyncio.sleep(0.01)
        assert FakeSequence.seen == []                 # blocked behind the job
    await task
    assert len(FakeSequence.seen) == 1


# ── the reconcile seam ───────────────────────────────────────────────────

class Seam:
    def __init__(self):
        self.calls, self.order = [], []

    async def fetch_tabs(self):
        return []

    async def join_tab(self, ws):
        pass

    def leave_tab(self, tab_id):
        self.order.append("leave")
        return True

    def identify(self, tabs, manual):
        self.order.append("identify")
        self.calls.append((list(tabs or []), manual))


def _bridge(tmp_path):
    from app.browser.page_pool import PagePool
    from tests.characterization.harness import CORE_STACK, build_bridge, build_stack
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge._page_pool = PagePool(logger=lambda m, l="info": None)
    return env.bridge


@pytest.mark.asyncio
async def test_every_pass_hands_its_rows_to_identify_with_the_manual_flag(tmp_path):
    bridge, seam = _bridge(tmp_path), Seam()
    deps = rc.LiveDeps(fetch_tabs=seam.fetch_tabs, join_tab=seam.join_tab, commit=lambda: None,
                       log=lambda *a, **k: None, leave_tab=seam.leave_tab, identify=seam.identify)
    await rc.reconcile_once(bridge, deps, "auto")
    await rc.reconcile_once(bridge, deps, "manual")
    assert [manual for _tabs, manual in seam.calls] == [False, True]


@pytest.mark.asyncio
async def test_a_pass_without_the_seam_never_identifies(tmp_path):
    bridge, seam = _bridge(tmp_path), Seam()
    deps = rc.LiveDeps(fetch_tabs=seam.fetch_tabs, join_tab=seam.join_tab, commit=lambda: None,
                       log=lambda *a, **k: None)
    await rc.reconcile_once(bridge, deps, "auto")
    assert seam.calls == []


def test_live_deps_wires_the_firefox_identity_observer():
    bridge = SimpleNamespace(_log=lambda *a, **k: None)
    deps = browser_tabs.live_deps(bridge)
    assert deps.identify.func is browser_tabs.firefox_identity.observe
    assert deps.identify.args == (bridge,)
