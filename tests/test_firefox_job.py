"""`services/firefox_job` — one serial Ui.Vision macro run per dispatched job (D-7).

The orchestration is tested at its documented choke (`_seams` / `_execute`):
a fake executor proves the serial lock, the configured inter-run gap, the
stop/cancel honesty and the verdict mapping; the real executor's own steps
(provision/launch/savelog) live under the existing `test_uivision_*` files.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.browser.page_status import PageInfo
from app.browser.uivision.discovery import FirefoxTab
from app.persistence.config_manager import ConfigManager
from app.services import firefox_job as fj

pytestmark = pytest.mark.unit


def make_bridge(tmp_path, **kw):
    ns = {"_log": lambda m, l="info": None, "config": ConfigManager(str(tmp_path / "cfg")),
          "_cancel_requested": False, **kw}
    return SimpleNamespace(**ns)


def save_gap(bridge, seconds):
    bridge.config.set_state(**{"firefox_auto": {"inter_run_delay_sec": seconds}})


def ff_page(tab_id="9THrgpBc.Profile1_tab0"):
    return PageInfo(tab_id=tab_id, url="https://chatgpt.com/", title="ChatGPT",
                    browser="firefox", profile="/profiles/9THrgpBc.Profile1")


def ff_tab(title="ChatGPT"):
    return FirefoxTab(id="9THrgpBc.Profile1_tab0", url="https://chatgpt.com/",
                      title=title, profile_dir="/profiles/9THrgpBc.Profile1",
                      profile_name="Profile1", tab_index=0, windows=("w",))


class Pool:
    """The two members this module touches (RULE 4: nothing else)."""

    def __init__(self, page=None):
        self.page = page
        self._aborts = set()

    def get_page(self, tab_id):
        return self.page if (self.page and self.page.tab_id == tab_id) else None


def fake_execute(calls, result=None, fail=False):
    async def _execute(bridge, spec, target, stopped):
        calls.append((spec, target, stopped()))
        if fail:
            raise RuntimeError("executor exploded")
        return result or SimpleNamespace(kind="ok", message="")
    return _execute


def use_tab(monkeypatch, title="ChatGPT"):
    async def find(_page):
        return ff_tab(title)
    monkeypatch.setattr(fj, "_find_target", find)


# ── gap / lock / stop ────────────────────────────────────────────────────────

def test_gap_is_computed_from_the_monotone_run_clock():
    bridge = SimpleNamespace()
    now = time.monotonic()
    assert fj._pending_gap(bridge, 3.0) == 0.0              # first run owes nothing
    bridge._ff_last_run_end = now - 1.0
    assert 1.9 <= fj._pending_gap(bridge, 3.0, now=now) <= 2.1
    assert fj._pending_gap(bridge, 0.0, now=now) == 0.0      # delay 0 = no gap
    bridge._ff_last_run_end = now + 50.0                     # clock reset ahead
    assert fj._pending_gap(bridge, 3.0, now=now) == 3.0      # …never a runaway wait


def test_the_gap_comes_from_the_stored_config_with_the_owners_default(tmp_path):
    bridge = make_bridge(tmp_path)
    assert fj._gap_seconds(bridge) == fj.DEFAULT_GAP_SEC == 3.0
    save_gap(bridge, 7)
    assert fj._gap_seconds(bridge) == 7.0
    broken = SimpleNamespace(config=object())               # unreadable state heals
    assert fj._gap_seconds(broken) == fj.DEFAULT_GAP_SEC


@pytest.mark.asyncio
async def test_the_wait_returns_at_once_once_the_gap_is_expired(tmp_path):
    bridge = make_bridge(tmp_path)
    bridge._ff_last_run_end = time.monotonic() - 60
    started = time.monotonic()
    await fj._await_gap(bridge, 3.0, lambda: False)
    assert time.monotonic() - started < 1.0


@pytest.mark.asyncio
async def test_the_wait_stops_as_soon_as_the_stop_predicate_fires(tmp_path):
    bridge = make_bridge(tmp_path)
    bridge._ff_last_run_end = time.monotonic()              # gap running…
    started = time.monotonic()
    await fj._await_gap(bridge, 30.0, lambda: True)         # …but stop wins at once
    assert time.monotonic() - started < 1.0


def test_the_bridge_lock_is_created_once_and_reused():
    bridge = SimpleNamespace()
    first = fj._macro_lock(bridge)
    assert isinstance(first, asyncio.Lock)
    assert fj._macro_lock(bridge) is first


def test_the_runner_seams_carry_the_stop_predicate():
    seams = fj._seams(lambda: True)
    assert seams.stop() is True
    assert seams.sleep is None and seams.popen is None      # real defaults stay real


# ── verdicts and honest failures ─────────────────────────────────────────────

def test_the_verdict_maps_ok_and_names_every_other_kind():
    assert fj._verdict(SimpleNamespace(kind="ok", message="")) == (False, "")
    failed, err = fj._verdict(SimpleNamespace(kind="error", message="log unreadable"))
    assert failed and err == "error: log unreadable"
    failed, err = fj._verdict(SimpleNamespace(kind="blocked", message="no profile"))
    assert failed and err == "blocked: no profile"


@pytest.mark.asyncio
async def test_a_pool_page_that_vanished_fails_by_name(tmp_path):
    failed, err = await fj.run_macro_job(make_bridge(tmp_path), Pool(None),
                                          "9THrgpBc.Profile1_tab0")
    assert failed and "left the pool" in err


@pytest.mark.asyncio
async def test_a_cancelled_run_never_launches(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, _cancel_requested=True)
    called = []
    monkeypatch.setattr(fj, "_execute", fake_execute(called))
    failed, err = await fj.run_macro_job(bridge, Pool(ff_page()), ff_page().tab_id)
    assert failed and "stopped" in err and called == []


@pytest.mark.asyncio
async def test_a_closed_tab_fails_by_name_and_never_launches(tmp_path, monkeypatch):
    async def find(_page):
        return None
    called = []
    monkeypatch.setattr(fj, "_find_target", find)
    monkeypatch.setattr(fj, "_execute", fake_execute(called))
    failed, err = await fj.run_macro_job(make_bridge(tmp_path), Pool(ff_page()),
                                         ff_page().tab_id)
    assert failed and "no longer open" in err and called == []


@pytest.mark.asyncio
async def test_an_untitled_tab_cannot_be_addressed(tmp_path, monkeypatch):
    async def find(_page):
        return ff_tab(title="   ")
    called = []
    monkeypatch.setattr(fj, "_find_target", find)
    monkeypatch.setattr(fj, "_execute", fake_execute(called))
    failed, err = await fj.run_macro_job(make_bridge(tmp_path), Pool(ff_page()),
                                         ff_page().tab_id)
    assert failed and "no title" in err and called == []


@pytest.mark.asyncio
async def test_a_row_with_a_non_firefox_page_fails_by_name(tmp_path):
    page = PageInfo(tab_id="x1", url="https://arena.ai", browser="chrome")
    failed, err = await fj.run_macro_job(make_bridge(tmp_path), Pool(page), "x1")
    assert failed and "left the pool" in err


# ── the happy path, serialised ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_successful_run_reports_success_and_stamps_the_run_clock(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    save_gap(bridge, 0)
    calls = []
    monkeypatch.setattr(fj, "_find_target",
                        lambda p: asyncio.sleep(0, result=ff_tab()))
    monkeypatch.setattr(fj, "_execute", fake_execute(calls))
    failed, err = await fj.run_macro_job(bridge, Pool(ff_page()), ff_page().tab_id)
    assert (failed, err) == (False, "")
    assert bridge._ff_last_run_end > 0
    spec, target, was_stopped = calls[0]
    assert was_stopped is False
    assert spec.url_pattern == "https://chatgpt.com/"        # locator = the pool row's URL
    assert spec.pattern == ""                                 # no owner title filter
    assert spec.selected_profiles == ("/profiles/9THrgpBc.Profile1",)
    assert target.profile_name == "Profile1"


@pytest.mark.asyncio
async def test_two_runs_never_overlap_on_one_machine(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    save_gap(bridge, 0)
    active = {"n": 0, "max": 0}
    calls = []

    async def slow(bridge_, spec, target, stopped):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        await asyncio.sleep(0.02)
        active["n"] -= 1
        calls.append(1)
        return SimpleNamespace(kind="ok", message="")

    monkeypatch.setattr(fj, "_find_target",
                        lambda p: asyncio.sleep(0, result=ff_tab()))
    monkeypatch.setattr(fj, "_execute", slow)
    pool = Pool(ff_page())
    await asyncio.gather(fj.run_macro_job(bridge, pool, ff_page().tab_id),
                         fj.run_macro_job(bridge, pool, ff_page().tab_id))
    assert active["max"] == 1 and len(calls) == 2


@pytest.mark.asyncio
async def test_unexpected_executor_errors_propagate_but_the_clock_still_stamps(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    save_gap(bridge, 0)
    monkeypatch.setattr(fj, "_find_target",
                        lambda p: asyncio.sleep(0, result=ff_tab()))
    monkeypatch.setattr(fj, "_execute", fake_execute([], fail=True))
    with pytest.raises(RuntimeError, match="exploded"):
        await fj.run_macro_job(bridge, Pool(ff_page()), ff_page().tab_id)
    assert bridge._ff_last_run_end > 0


@pytest.mark.asyncio
async def test_a_failed_verdict_stamps_the_clock_for_the_next_gap(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    save_gap(bridge, 0)
    monkeypatch.setattr(fj, "_find_target",
                        lambda p: asyncio.sleep(0, result=ff_tab()))
    monkeypatch.setattr(fj, "_execute", fake_execute(
        [], result=SimpleNamespace(kind="error", message="savelog missing")))
    failed, err = await fj.run_macro_job(bridge, Pool(ff_page()), ff_page().tab_id)
    assert failed and err == "error: savelog missing"
    assert bridge._ff_last_run_end > 0, "the gap counts from the run's end either way"


@pytest.mark.asyncio
async def test_the_row_stop_flag_fails_the_run_before_the_macro(tmp_path):
    bridge = make_bridge(tmp_path)
    save_gap(bridge, 0)
    pool = Pool(ff_page())
    pool._aborts.add(ff_page().tab_id)
    failed, err = await fj.run_macro_job(bridge, pool, ff_page().tab_id)
    assert failed and "stopped" in err
