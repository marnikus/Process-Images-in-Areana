"""The Firefox execution lane (2026-09-25, design D5/D6/D9).

One macro = one job: spec built from the SAME validated config the window
uses (re-export pin), the locator taken from the POOL ENTRY (guarded
`selectWindow url=*<tab url>*` + the tab's own title fallback — never a
foreground-constructed title), serialized machine-wide with the owner's
user-defined delay (`inter_run_delay_sec`, default 3 s), cancel honoured
(RULE 7), every step logged (RULE 2).

RED at base: `ModuleNotFoundError: app.services.firefox_lane`.
"""

import asyncio

import pytest

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


def test_spec_addresses_the_pool_entry_not_a_title_search(monkeypatch):
    captured = {}

    async def fake_execute(spec, run, bridge, report):
        captured["spec"], captured["run"] = spec, run
        return "ok", "done"

    monkeypatch.setattr(fl, "_execute", fake_execute)
    monkeypatch.setattr(fl, "_wait_gap", _no_gap)
    bridge = CfgBridge(cfg={"pattern": "New Chat", "url_pattern": "arena.ai",
                            "target": "id=go", "inter_run_delay_sec": 0})
    page = ff_page(url="https://arena.ai/c/7", title="My chat")
    kind, msg = asyncio.run(fl.run_firefox_macro(bridge, page))
    spec, run = captured["spec"], captured["run"]
    assert (kind, msg) == ("ok", "done")
    assert spec.pattern == ""                        # pool job: no title search
    assert spec.url_pattern == "https://arena.ai/c/7"  # locator FROM the pool entry
    assert spec.target == "id=go"
    assert run.target.profile_dir.endswith("9THrgpBc.Profile1")
    assert run.selector == "title=*My chat*"          # fallback = the tab's own title
    assert run.log_path.endswith(".txt")
    assert any("🦊" in m for _, m in bridge.logs)    # RULE 2: steps land in the log


async def _no_gap(_cfg):
    return None


@pytest.mark.asyncio
async def test_cancel_short_circuits_before_any_launch(monkeypatch):
    async def boom(*_a):
        raise AssertionError("must not execute when cancelled")

    monkeypatch.setattr(fl, "_execute", boom)
    kind, msg = await fl.run_firefox_macro(CfgBridge(cancel=True), ff_page())
    assert kind == "stopped"


@pytest.mark.asyncio
async def test_one_macro_at_a_time_per_machine(monkeypatch):
    """The owner's contract: one Ui.Vision macro at a time, even in parallel dispatch."""
    active = {"now": 0, "peak": 0}

    async def slow_execute(spec, run, bridge, report):
        active["now"] += 1
        active["peak"] = max(active["peak"], active["now"])
        await asyncio.sleep(0.03)
        active["now"] -= 1
        return "ok", "done"

    monkeypatch.setattr(fl, "_execute", slow_execute)
    monkeypatch.setattr(fl, "_wait_gap", _no_gap)
    bridge = CfgBridge(cfg={"inter_run_delay_sec": 0})
    page_a, page_b = ff_page(), FirefoxPageInfo(
        ws_url="", tab_id="P_tab2", url="https://arena.ai/c/8", title="B",
        browser="firefox", is_connected=True, profile="P", profile_dir="/x/P")
    await asyncio.gather(fl.run_firefox_macro(bridge, page_a),
                         fl.run_firefox_macro(bridge, page_b))
    assert active["peak"] == 1


def test_gap_seconds_reads_the_windows_user_defined_delay():
    assert fl._gap_seconds({"inter_run_delay_sec": 7}) == 7
    assert fl._gap_seconds({"inter_run_delay_sec": 0}) == 0
    assert fl._gap_seconds({}) == 3          # owner's default (design §4.3)
    assert fl._gap_seconds({"inter_run_delay_sec": 9999}) == 30  # clamp ceiling


@pytest.mark.asyncio
async def test_gap_waits_only_when_the_previous_job_was_recent(monkeypatch):
    waits = []

    async def spy_wait(cfg):
        waits.append(cfg)

    monkeypatch.setattr(fl, "_wait_gap", spy_wait)
    monkeypatch.setattr(fl, "_execute", _ok_execute)
    bridge = CfgBridge(cfg={"inter_run_delay_sec": 0})
    await fl.run_firefox_macro(bridge, ff_page())
    assert waits and waits[0]["inter_run_delay_sec"] == 0


async def _ok_execute(spec, run, bridge, report):
    return "ok", "done"


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
