"""The Firefox execution lane (2026-09-25, design D5/D6/D9).

One phase macro on one pool entry (image job D-1): spec built from the SAME
validated config the window uses (re-export pin), retargeted at the phase
macro; the locator taken from the POOL ENTRY (guarded `selectWindow
url=*<tab url>*` + the tab's own title fallback — never a foreground-
constructed title); serialized machine-wide; the owner's user-defined delay
(`inter_run_delay_sec`, default 3 s) only BETWEEN jobs.

RED at base: `ModuleNotFoundError: app.services.firefox_lane`.
"""

import asyncio

import pytest

from app.browser.uivision import job_macros as uv_job
from app.browser.uivision.pool_tabs import FirefoxPageInfo
from app.services import firefox_lane as fl
from app.ui.panels import firefox_auto as fa

pytestmark = pytest.mark.unit


class CfgBridge:
    """Minimal duck-typed bridge: config reads + log capture + cancel flag."""

    def __init__(self, cfg=None, cancel=False):
        stored = {"firefox_auto": dict(cfg or {})}
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


def test_reexports_are_the_same_functions_the_window_saves():
    """RULE 10: one validation/spec builder — the panel and the lane share it."""
    assert fa.validate_config is fl.uv_config.validate_config
    assert fa.build_spec is fl.uv_config.build_spec
    assert fa.load_config is fl.uv_config.load_config


def phase(name="baseline"):
    return uv_job.probe_macro("c1", name, "1")


def test_spec_addresses_the_pool_entry_not_a_title_search(monkeypatch, tmp_path):
    captured = {}

    async def fake_locked(spec, run, provision):
        captured["spec"], captured["run"], captured["provision"] = spec, run, provision
        return "ok", "done", ("[echo] x",)

    monkeypatch.setattr(fl, "_run_locked", fake_locked)
    bridge = CfgBridge(cfg={"pattern": "New Chat", "url_pattern": "arena.ai", "storage": "xfile",
                            "target": "id=go", "inter_run_delay_sec": 0})
    bridge.config.dir = str(tmp_path)
    page = ff_page(url="https://arena.ai/c/7", title="My chat")
    attach = uv_job.attach_macro("c1", "C:/up/arena_c1.png", "1")
    kind, msg, lines = asyncio.run(fl.run_phase(bridge, page, attach, "c1"))
    spec, run = captured["spec"], captured["run"]
    assert (kind, msg, lines) == ("ok", "done", ("[echo] x",))
    assert spec.macro == attach.name == "Arena_Job_Attach"   # the PHASE macro, not the window's
    assert spec.target == attach.xclick                      # cmd_var2 = the native-click target
    assert spec.pause_ms == attach.wait_ms and spec.timeout_sec == attach.timeout_sec
    assert spec.pattern == ""                                # pool job: no title search
    assert spec.url_pattern == "https://arena.ai/c/7"        # locator FROM the pool entry
    assert run.target.profile_dir.endswith("9THrgpBc.Profile1")
    assert run.selector == "title=*My chat*"                 # fallback = the tab's own title
    assert "c1" in run.log_path and run.log_path.endswith(".txt")


@pytest.mark.asyncio
async def test_browser_storage_is_blocked_before_any_launch(monkeypatch):
    """The job writes its phase macros to disk — browser storage answers `blocked` (RULE 4)."""
    async def boom(*_a):
        raise AssertionError("must not launch with browser storage")

    monkeypatch.setattr(fl, "_run_locked", boom)
    kind, msg, lines = await fl.run_phase(CfgBridge(cfg={"storage": "browser"}), ff_page(), phase(), "c1")
    assert kind == "blocked" and "xfile" in msg and lines == ()


class SlowSequence:
    """Sequence stand-in for the lock test only (the real one runs in the real-sequence tests)."""

    active = {"now": 0, "peak": 0}

    def __init__(self, spec, seams, recorder):
        self.page = None

    async def execute(self, runs):
        self.active["now"] += 1
        self.active["peak"] = max(self.active["peak"], self.active["now"])
        await asyncio.sleep(0.03)
        self.active["now"] -= 1
        return type("R", (), {"kind": "ok", "message": "done", "lines": []})()


@pytest.mark.asyncio
async def test_one_macro_at_a_time_per_machine(monkeypatch, tmp_path):
    """The owner's contract: one Ui.Vision macro at a time, even across parallel jobs."""
    monkeypatch.setattr(fl, "_MACRO_LOCK", asyncio.Lock())
    monkeypatch.setattr(fl, "Sequence", SlowSequence)
    monkeypatch.setattr(SlowSequence, "active", {"now": 0, "peak": 0})
    monkeypatch.setattr(fl.uv_job, "provision", lambda spec, ph: "page.html")
    monkeypatch.setattr(fl.uv_tabs, "profile_sessions", lambda profiles=None: [])
    bridge = CfgBridge(cfg={"inter_run_delay_sec": 0, "storage": "xfile"})
    bridge.config.dir = str(tmp_path)
    page_b = FirefoxPageInfo(ws_url="", tab_id="P_tab2", url="https://arena.ai/c/8", title="B",
                             browser="firefox", is_connected=True, profile="P", profile_dir="/x/P")
    await asyncio.gather(fl.run_phase(bridge, ff_page(), phase(), "c1"),
                         fl.run_phase(bridge, page_b, phase(), "c2"))
    assert SlowSequence.active["peak"] == 1


def test_gap_seconds_reads_the_windows_user_defined_delay():
    assert fl._gap_seconds({"inter_run_delay_sec": 7}) == 7
    assert fl._gap_seconds({"inter_run_delay_sec": 0}) == 0
    assert fl._gap_seconds({}) == 3          # owner's default (design §4.3)
    assert fl._gap_seconds({"inter_run_delay_sec": 9999}) == 30  # clamp ceiling


@pytest.mark.asyncio
async def test_job_gap_reads_the_owner_delay_and_note_job_end_stamps(monkeypatch):
    """Owner Q4: the delay sits BETWEEN JOBS — `job_gap` before, `note_job_end` after."""
    waits = []

    async def spy_wait(cfg):
        waits.append(cfg)

    monkeypatch.setattr(fl, "_wait_gap", spy_wait)
    monkeypatch.setattr(fl, "_LAST_AT", 0.0)
    await fl.job_gap(CfgBridge(cfg={"inter_run_delay_sec": 5}))
    assert waits and waits[0]["inter_run_delay_sec"] == 5
    fl.note_job_end()
    assert fl._LAST_AT > 0


async def test_default_sleep_is_the_real_seam_default():
    """The injected fast seam hides the production fallback — drive it once (cover import+await)."""
    from app.browser.uivision import runner
    await runner._default_sleep(0)


def test_provision_is_the_public_face_the_pool_lane_calls(monkeypatch):
    """`firefox_lane` provisions through this wrapper — one call keeps it honest."""
    from app.browser.uivision import runner
    sentinel = object()
    monkeypatch.setattr(runner, "_provision", lambda spec, report: sentinel)
    assert runner.provision("spec", "report") is sentinel


@pytest.mark.asyncio
async def test_wait_gap_sleeps_out_the_remaining_delay(monkeypatch):
    """Drive the REAL _wait_gap (the other test stubs it) with a just-finished job."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(fl, "asyncio", type("A", (), {"sleep": staticmethod(fake_sleep)})())
    monkeypatch.setattr(fl, "_LAST_AT", fl.time.monotonic())   # a job just ended
    await fl._wait_gap({"inter_run_delay_sec": 7})
    assert slept and 0 < slept[0] <= 7


def test_gap_seconds_survives_a_garbage_value():
    assert fl._gap_seconds({"inter_run_delay_sec": "soon"}) == 3


def test_target_windows_are_this_profiles_only(monkeypatch):
    sessions = [{"dir": "/x/other", "windows": ["W0"]},
                {"dir": "/x/9THrgpBc.Profile1", "windows": ["W1", "W2"]}]
    monkeypatch.setattr(fl.uv_tabs, "profile_sessions", lambda profiles=None: sessions)
    assert fl._target_windows(ff_page()) == ("W1", "W2")
    monkeypatch.setattr(fl.uv_tabs, "profile_sessions", lambda profiles=None: sessions[:1])
    assert fl._target_windows(ff_page()) == ()


def test_fresh_drops_a_stale_savelog_and_tolerates_a_locked_one(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    stale = tmp_path / "log.txt"
    stale.write_text("Status=OK", encoding="utf-8")
    run = NS(log_path=str(stale))
    assert fl._fresh(run) is run and not stale.exists()

    def locked(self, missing_ok=False):
        raise PermissionError("in use")

    monkeypatch.setattr(fl.Path, "unlink", locked)
    assert fl._fresh(run) is run
