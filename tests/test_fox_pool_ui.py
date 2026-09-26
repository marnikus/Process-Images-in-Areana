"""I-64 · Firefox in the one pool — the ui-land wiring on a real Bridge.

Merged listing semantics (Chrome-only answers pass unchanged when no Firefox
profile is checked), the id join without a CDP client, the per-job planner
(fresh read → title + relative index), the lane install, the JOBS edit that
survives the store's max-merge, typed URL rows, and the framework test
sharing the machine gate. Session docs are faked at `ScanSeams`.
"""

import json
from types import SimpleNamespace

import pytest

from app.browser.page_status import PageInfo
from app.browser.uivision import runner as uiv_runner
from app.browser.uivision.plan import Patterns
from app.browser.uivision.pool.scan import FoxScanner, ScanSeams
from app.browser.uivision.sequence import RunResult
from app.core.models import UrlRow
from app.persistence.cooldown_store import load_entries, load_stats, save_entries, set_job_count
from app.services.live.reconcile import ScanUnavailable
from app.services.run_state import cooldowns_path
from app.services.uivision_job import uivision_gate
from app.ui.panels import browser_tabs, firefox_auto, page_pool
from app.ui.services import firefox_pool as fp
from app.ui.services.undo_entries import arena_url_rows_from_js, url_rows_from_js
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack
from tests.test_live_reconcile import tab

pytestmark = pytest.mark.unit

PROF = "/ff/Profiles/9THrgpBc.Profile1"
FOX = "9THrgpBc.Profile1_tab1"
FOX2 = "9THrgpBc.Profile1_tab2"


def doc(*windows):
    return {"windows": [{"selected": 1, "tabs": [{"entries": [{"url": u, "title": t}], "index": 1}
                                                  for u, t in window]} for window in windows]}


def fox(tab_id=FOX, url="https://arena.ai/c/7"):
    return SimpleNamespace(id=tab_id, url=url, title="LMArena", ws_url="", conn="uivision", type="page")


def make_env(tmp_path, docs=None, **cfg):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    from app.browser.page_pool import PagePool
    env.bridge._page_pool = PagePool()
    stored = {"selected_profiles": [PROF], "target": "xpath=//b", "storage": "xfile",
              "pause_ms": 2000, "timeout_sec": 60, "macro": "Python_XClick_Demo"}
    stored.update(cfg)
    env.cfg.set_state(firefox_auto=stored, url_pattern="arena.ai")
    if docs is not None:
        env.bridge._fox_scanner = FoxScanner(seams=ScanSeams(
            in_use=lambda p: True, names=lambda: {PROF: "Profile1"},
            doc=lambda p: (docs[p], 1.0, "recovery.jsonlz4") if p in docs else (None, -1.0, "")))
    return env


def logs(env):
    return [call[0] for call in env.recs["arena_log"].calls]


async def chrome_ok():
    return [tab("C1")]


async def chrome_empty():
    return []


async def chrome_down():
    raise ScanUnavailable("port 9222 closed")


@pytest.mark.asyncio
async def test_no_checked_profile_passes_chromes_own_answer_unchanged(tmp_path):
    env = make_env(tmp_path, selected_profiles=[])
    got = await fp.merged_listing(env.bridge, chrome_ok)
    assert got == [tab("C1")] and type(got) is list
    with pytest.raises(ScanUnavailable, match="9222"):
        await fp.merged_listing(env.bridge, chrome_down)


@pytest.mark.asyncio
async def test_the_merge_holds_exactly_what_a_silent_or_empty_browser_owns(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    env.bridge.state.urls = [UrlRow.create("https://arena.ai/c/1", tab_id="C1"),
                             UrlRow.create("https://arena.ai/c/7", tab_id=FOX)]

    async def fox_ok(bridge):
        return [fox()]
    monkeypatch.setattr(fp, "firefox_tabs", fox_ok)
    both = await fp.merged_listing(env.bridge, chrome_ok)
    assert [t.id for t in both] == ["C1", FOX] and both.held_rows == frozenset() and both.answered
    empty = await fp.merged_listing(env.bridge, chrome_empty)
    assert empty.held_rows == {"C1"} and empty.held_pages == frozenset()
    silent = await fp.merged_listing(env.bridge, chrome_down)
    assert silent.held_rows == {"C1"} and silent.held_pages == {"C1"}

    async def fox_boom(bridge):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(fp, "firefox_tabs", fox_boom)
    broken = await fp.merged_listing(env.bridge, chrome_ok)
    assert broken.held_pages == {FOX} and not broken.answered
    await fp.merged_listing(env.bridge, chrome_ok)
    assert sum("scan failed (RuntimeError: disk gone)" in m for m in logs(env)) == 1
    with pytest.raises(ScanUnavailable, match="neither"):
        await fp.merged_listing(env.bridge, chrome_down)


@pytest.mark.asyncio
async def test_firefox_tabs_scan_the_checked_profiles_and_log_a_note_once(tmp_path):
    docs = {}
    env = make_env(tmp_path, docs)
    assert await fp.firefox_tabs(env.bridge) == []
    await fp.firefox_tabs(env.bridge)
    assert sum(m.startswith("🦊 Firefox scan: Profile1: no readable") for m in logs(env)) == 1
    docs[PROF] = doc([("https://arena.ai/c/7", "LMArena")])
    assert [t.id for t in await fp.firefox_tabs(env.bridge)] == [FOX]
    assert fp.patterns_of({"pattern": "A", "url_pattern": "b"}) == Patterns("A", "b")


def test_the_scanner_is_created_once_and_seeded_from_the_rows(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge.state.urls = [UrlRow.create("https://arena.ai/c/9", tab_id="9THrgpBc.Profile1_tab5"),
                             UrlRow.create("https://arena.ai/c/1", tab_id="C1")]
    scanner = fp.fox_scanner(env.bridge)
    assert scanner is fp.fox_scanner(env.bridge)
    assert scanner.book.known_ids("9THrgpBc.Profile1") == ["9THrgpBc.Profile1_tab5"]


@pytest.mark.asyncio
async def test_a_discovered_firefox_tab_joins_without_a_cdp_client(tmp_path):
    env = make_env(tmp_path, {PROF: doc([("https://arena.ai/c/7", "LMArena")])})
    fp.fox_scanner(env.bridge).scan([PROF], Patterns())
    assert await fp.join_firefox(env.bridge, FOX) is True
    page = env.bridge._page_pool.get_page(FOX)
    assert (page.browser, page.profile, page.ws_url) == ("firefox", "Profile1", "")
    assert page.alias.startswith("Profile1_") and page.is_connected
    assert env.bridge._page_pool.get_clients(FOX) == (None, None)
    assert any(m.startswith("✅ Pool added Profile1_") for m in logs(env))
    assert await fp.join_firefox(env.bridge, "9THrgpBc.Profile1_tab9") is False
    assert any("Firefox join skipped" in m for m in logs(env))


@pytest.mark.asyncio
async def test_joins_and_rejoins_route_by_the_key_shape(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    seen = []

    async def fake_fox(bridge, tab_id):
        seen.append(("fox", tab_id))
        return True

    async def fake_cdp(bridge, ws):
        seen.append(("cdp", ws))
    monkeypatch.setattr(fp, "join_firefox", fake_fox)
    monkeypatch.setattr(page_pool, "do_connect_page_pool", fake_cdp)
    await fp.join_any(env.bridge, FOX)
    await fp.join_any(env.bridge, "ws://127.0.0.1:9222/devtools/page/C1")
    assert await page_pool._rejoin_one(env.bridge, env.bridge._page_pool, {}, FOX2) is True
    assert seen == [("fox", FOX), ("cdp", "ws://127.0.0.1:9222/devtools/page/C1"), ("fox", FOX2)]


def test_the_planner_reads_fresh_and_bakes_title_plus_relative_index(tmp_path):
    docs = {PROF: doc([("https://arena.ai/c/1", "LMArena"), ("https://arena.ai/c/2", "LMArena")])}
    env = make_env(tmp_path, docs)
    fp.fox_scanner(env.bridge).scan([PROF], Patterns())
    job = fp.plan_job(env.bridge, FOX2)
    assert (job.step.anchor, job.step.offset, job.step.needle) == ("LMArena", 1, "arena.ai")
    assert (job.step.target, job.step.pause_ms) == ("xpath=//b", 2000)
    assert (job.spec.macro, job.spec.storage, job.spec.timeout_sec) == ("Python_XClick_Demo_pool", "xfile", 60)
    assert job.tab.index == 1 and job.window_row["index"] == 1
    assert "not in the last Firefox scan" in fp.plan_job(env.bridge, "9THrgpBc.Profile1_tab9")
    docs[PROF] = doc([("https://arena.ai/c/1", "LMArena")], [("https://arena.ai/c/2", "LMArena")])
    assert "FIRST match" in fp.plan_job(env.bridge, FOX2)             # moved behind a shared title
    docs[PROF] = doc([("https://other.org", "X")])
    assert "gone from its profile's session store" in fp.plan_job(env.bridge, FOX2)


@pytest.mark.asyncio
async def test_install_hands_the_lane_its_planner_runner_and_delay(tmp_path, monkeypatch):
    env = make_env(tmp_path, inter_run_delay_sec=7)
    deps = fp.install(env.bridge)
    assert env.bridge._uivision_deps is deps and deps.delay_sec() == 7.0
    assert deps.plan.func is fp.plan_job and deps.plan.args == (env.bridge,) and deps.run is fp.run_job
    seen = {}

    async def fake_run(job, report, seams):
        seen.update(job=job, stop=seams.stop())
        return "R"
    monkeypatch.setattr(fp, "run_pool_job", fake_run)
    assert await fp.run_job("J", print, lambda: True) == "R" and seen == {"job": "J", "stop": True}
    monkeypatch.setattr(browser_tabs, "start_reconciler", lambda bridge, deps: True)
    env.bridge._uivision_deps = None
    assert browser_tabs.start_url_reconciler(env.bridge) and env.bridge._uivision_deps is not None


def test_a_lowered_jobs_count_survives_the_stores_max_merge(tmp_path):
    env = make_env(tmp_path)
    bridge, pool = env.bridge, env.bridge._page_pool
    pool.add_page(PageInfo(tab_id=FOX, url="https://arena.ai/c/7", browser="firefox", profile="Profile1",
                           jobs_completed=7))
    bridge._persist_cooldowns()
    path = cooldowns_path(bridge)
    assert load_stats(path)["https://arena.ai/c/7"]["jobs_completed"] == 7
    assert json.loads(bridge.set_page_jobs(FOX, 3)) == {"ok": True, "jobs": 3}
    bridge._persist_cooldowns()                                        # a max-merge would bring 7 back
    assert pool.get_page(FOX).jobs_completed == 3
    assert load_stats(path)["https://arena.ai/c/7"]["jobs_completed"] == 3
    assert json.loads(bridge.set_page_jobs(FOX, -5))["jobs"] == 0
    assert json.loads(bridge.set_page_jobs("nope", 1)) == {"ok": False, "error": "tab not in pool"}
    bad = json.loads(bridge.set_page_jobs(FOX, "x"))                  # a broken count never raises into Qt
    assert bad["ok"] is False and "invalid literal" in bad["error"]
    assert any(m.startswith("✏ Jobs for Profile1_") and m.endswith(" set to 3") for m in logs(env))


def test_set_job_count_overwrites_one_counter_and_keeps_the_timers(tmp_path):
    path = tmp_path / "cooldowns.json"
    save_entries(path, {"T1": {"tab_id": "T1", "url": "u", "cooldown_until": 9e12, "saved_at": 1.0}})
    assert set_job_count(path, "https://Arena.ai/c/1/", 4) is True
    assert load_stats(path) == {"https://arena.ai/c/1": {"jobs_completed": 4}}
    assert "T1" in load_entries(path)
    assert set_job_count(path, "  ", 4) is False


def test_typed_urls_stay_typed_through_add_edit_and_undo(tmp_path):
    env = make_env(tmp_path)
    added = json.loads(env.bridge.add_url("https://arena.ai/c/42"))
    row = next(u for u in env.bridge.state.urls if u.id == added["id"])
    assert row.typed is True
    auto = UrlRow.create("https://arena.ai/c/1", tab_id="C1")
    env.bridge.state.urls.append(auto)
    assert json.loads(env.bridge.edit_url(auto.id, "https://arena.ai/c/43"))["ok"]
    assert (auto.typed, auto.url, auto.last_status) == (True, "https://arena.ai/c/43", "unchecked")
    assert url_rows_from_js([{"id": "a", "url": "u", "typed": True}])[0].typed is True
    assert arena_url_rows_from_js([{"id": "a", "url": "u", "typed": True}])[0].typed is True
    assert url_rows_from_js([{"id": "b", "url": "v"}])[0].typed is False


@pytest.mark.asyncio
async def test_the_framework_test_holds_the_machine_gate(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    bridge, order = env.bridge, []

    async def fake_run_test(spec, report, seams):
        order.append(("run", uivision_gate(bridge).busy))
        return RunResult(kind="ok", message="macro completed")
    monkeypatch.setattr(uiv_runner, "run_test", fake_run_test)
    spec = SimpleNamespace(inter_run_delay_sec=0)
    result = await firefox_auto._gated_run(bridge, spec, lambda *a: order.append(a))
    assert result.kind == "ok" and order == [("run", True)] and not uivision_gate(bridge).busy
    await uivision_gate(bridge).acquire(lambda: False)                 # a pool job holds the machine
    bridge._firefox_auto_stop = True
    stopped = await firefox_auto._gated_run(bridge, spec, lambda *a: order.append(a))
    assert stopped.kind == "stopped" and "Ui.Vision slot" in stopped.message
    assert order[-1][0] == "gate" and len([o for o in order if o[0] == "run"]) == 1
