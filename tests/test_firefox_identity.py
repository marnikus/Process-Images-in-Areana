"""Firefox worker names + visual tab id — lifecycle at the service seam.

`firefox_identity.observe` (the reconcile pass's `LiveDeps.identify`) decides
which pooled Firefox tabs are due; `drain` runs the identify macro through the
`run_identify` seam (faked here — the macro itself is covered by
`test_uivision_identify.py` + `tests/js/test_firefox_identify.mjs`).

Covered: temp name = profile (never `aka_…`), success, delayed load (retry
succeeds), missing element (fallback + bounded retries), macro failure/crash,
duplicate account names, reconnect, navigation, manual refresh, busy deferral,
stale-overlay clear, and the fallback chain's rungs.
"""

import json
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.uivision import pool_tabs as pt
from app.core.tab_alias import AliasBook
from app.services.live import firefox_identity as fi

pytestmark = pytest.mark.unit

EMAIL = "mailreceiverpro@gmail.com"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Runner:
    """Fake `run_identify`: scripted answers, records every payload."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    async def __call__(self, bridge, page, cmd_payload):
        self.calls.append((getattr(page, "tab_id", "") or getattr(page, "id", ""),
                           json.loads(cmd_payload)))
        answer = self.answers.pop(0) if self.answers else ok_reply(EMAIL)
        if isinstance(answer, Exception):
            raise answer
        return answer


def ok_reply(email="", no=1, name=""):
    text = f"{no}# {email or name}"
    line = "ARENA_IDENTITY=" + json.dumps({"email": email, "via": "scope",
                                           "overlay": "ok", "text": text})
    return "ok", "macro completed", ("[echo] " + line,)


def ff_tab(tab_id="A.Profile1_tab1", profile="Profile1", url="https://arena.ai/c/1"):
    return pt.FirefoxTab(id=tab_id, url=url, title="Arena", profile=profile,
                         profile_dir=f"/ff/{tab_id.split('_tab')[0]}", ws_url=pt.ws_for(tab_id))


@pytest.fixture
def env(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(fi, "_now", clock)
    scheduled = []

    def schedule(bridge, coro):
        scheduled.append(coro)
        coro.close()

    monkeypatch.setattr(fi, "schedule_coro", schedule)
    logs, emits = [], []
    pool = PagePool(logger=lambda m, l="info": None)
    bridge = SimpleNamespace(_page_pool=pool, _log=lambda m, l="info": logs.append((l, m)),
                             _emit_pool_status=lambda: emits.append(1))
    return SimpleNamespace(bridge=bridge, pool=pool, clock=clock, logs=logs,
                           emits=emits, scheduled=scheduled, mp=monkeypatch)


def join(env, *tabs):
    for tab in tabs:
        env.pool.add_page(pt.page_for(tab))
    return list(tabs)


def use(env, runner):
    env.mp.setattr(fi, "run_identify", runner)
    return runner


def warns(env):
    return [m for level, m in env.logs if level == "warn"]


# ── display name before / without detection ──────────────────────────────

def test_before_detection_the_profile_name_is_the_temp_label_never_aka(env):
    join(env, ff_tab())
    page = env.pool.get_page("A.Profile1_tab1")
    assert page.label == "Profile1" and "aka" not in page.label
    snap = env.pool.status_snapshot()["pages"][0]
    assert snap["tab_label"] == "Profile1" and snap["name_source"] == "profile"


def test_fallback_chain_saved_then_profile_dir_then_short_id():
    book = AliasBook({"A.P_tab1": {"no": 4, "email": EMAIL, "seen": 1.0}})
    pool = PagePool(logger=lambda m, l="info": None, alias_book=book)
    pool.add_page(pt.page_for(ff_tab("A.P_tab1", "")))
    saved = pool.get_page("A.P_tab1")
    assert (saved.label, saved.display_source) == (EMAIL, "saved")
    nameless = pt.page_for(ff_tab("B.default_tab2", ""))
    assert nameless.alias == "B.default"                  # profile dir basename
    bare = pt.FirefoxPageInfo(tab_id="C.x_tab9_long_technical_id")
    assert (bare.label, bare.display_source) == ("C.x_tab9_lon", "id")


# ── success / delayed load / missing element ─────────────────────────────

@pytest.mark.asyncio
async def test_first_sight_detects_the_account_and_labels_every_view(env):
    tabs = join(env, ff_tab())
    runner = use(env, Runner(ok_reply(EMAIL)))
    assert fi.observe(env.bridge, tabs) is True
    assert await fi.drain(env.bridge) == 1
    page = env.pool.get_page("A.Profile1_tab1")
    assert runner.calls == [("A.Profile1_tab1", {"no": 1, "name": "Profile1", "clear": False})]
    assert page.owner == EMAIL and page.display_source == "detected"
    assert page.label == EMAIL and fi.overlay_text(page) == f"1# {EMAIL}"
    assert env.pool.status_snapshot()["pages"][0]["tab_label"] == EMAIL
    assert env.pool._alias.owner_for("A.Profile1_tab1") == EMAIL        # persisted rung 2
    assert any(f"→ 1# {EMAIL}" in m for _l, m in env.logs) and env.emits
    assert page.name_checked_at > 0


@pytest.mark.asyncio
async def test_missing_element_warns_keeps_fallback_and_retries_bounded(env):
    tabs = join(env, ff_tab())
    use(env, Runner(*[ok_reply("", name="Profile1")] * 5))
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    first = warns(env)[0]
    for part in ("A.Profile1_tab1", "“Profile1”", "stage element", "first sight",
                 "showing “Profile1”", "retry 1/3 in 15s"):
        assert part in first
    delays = []
    for _ in range(3):
        track = fi.book_of(env.bridge).tracks["A.Profile1_tab1"]
        delays.append(track.due_at - env.clock.t)
        env.clock.t = track.due_at
        assert fi.observe(env.bridge, tabs) is True
        await fi.drain(env.bridge)
    assert delays == [15.0, 45.0, 120.0]
    assert "no more retries" in warns(env)[-1]
    assert fi.book_of(env.bridge).tracks["A.Profile1_tab1"].due_at is None
    env.clock.t += 10_000
    assert fi.observe(env.bridge, tabs) is False                  # rests until a trigger
    assert len(env.pool._pages) == 1 and env.pool.get_page("A.Profile1_tab1").label == "Profile1"


@pytest.mark.asyncio
async def test_delayed_load_second_attempt_succeeds(env):
    tabs = join(env, ff_tab())
    use(env, Runner(ok_reply("", name="Profile1"), ok_reply(EMAIL)))
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    assert env.pool.get_page("A.Profile1_tab1").label == "Profile1"
    env.clock.t += 15
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    assert env.pool.get_page("A.Profile1_tab1").label == EMAIL
    assert fi.book_of(env.bridge).tracks["A.Profile1_tab1"].attempts == 0


@pytest.mark.asyncio
async def test_macro_failure_and_crash_are_named_answers(env):
    tabs = join(env, ff_tab())
    use(env, Runner(("timeout", "no status\nline <div class='x'>page</div>", ()),
                    RuntimeError("boom")))
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    assert "stage macro" in warns(env)[0] and "timeout: no status line page" in warns(env)[0]
    assert "<" not in warns(env)[0]
    env.clock.t += 15
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    assert "identify crashed: RuntimeError" in warns(env)[1]
    assert len(env.pool._pages) == 1


@pytest.mark.asyncio
async def test_a_failed_redetection_never_regresses_a_known_account(env):
    tabs = join(env, ff_tab())
    use(env, Runner(ok_reply(EMAIL), ("error", "E210", ())))
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    fi.observe(env.bridge, tabs, manual=True)
    await fi.drain(env.bridge)
    assert env.pool.get_page("A.Profile1_tab1").label == EMAIL


# ── identity rules ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_same_account_in_two_profiles_stays_two_workers(env):
    tabs = join(env, ff_tab("A.P1_tab1", "P1"), ff_tab("B.P2_tab1", "P2"))
    use(env, Runner(ok_reply(EMAIL, 1), ok_reply(EMAIL, 2)))
    fi.observe(env.bridge, tabs)
    assert await fi.drain(env.bridge) == 2
    pages = env.pool._pages
    assert set(pages) == {"A.P1_tab1", "B.P2_tab1"}
    assert {fi.overlay_text(p) for p in pages.values()} == {f"1# {EMAIL}", f"2# {EMAIL}"}


# ── revalidation triggers ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_navigation_reconnect_and_manual_refresh_revalidate(env):
    tabs = join(env, ff_tab())
    runner = use(env, Runner())
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    assert fi.observe(env.bridge, tabs) is False                   # steady: nothing due
    moved = [ff_tab(url="https://arena.ai/c/2")]
    assert fi.observe(env.bridge, moved) is True
    page = env.pool.get_page("A.Profile1_tab1")
    assert page.url == "https://arena.ai/c/2"
    assert fi.book_of(env.bridge).tracks["A.Profile1_tab1"].reason == "navigation"
    await fi.drain(env.bridge)
    page.is_connected = False
    fi.observe(env.bridge, moved)
    page.is_connected = True
    fi.observe(env.bridge, moved)
    assert fi.book_of(env.bridge).tracks["A.Profile1_tab1"].reason == "reconnect"
    await fi.drain(env.bridge)
    fi.observe(env.bridge, moved, manual=True)
    assert fi.book_of(env.bridge).tracks["A.Profile1_tab1"].reason == "manual refresh"
    await fi.drain(env.bridge)
    assert len(runner.calls) == 4


@pytest.mark.asyncio
async def test_account_change_on_reload_updates_the_label(env):
    tabs = join(env, ff_tab())
    use(env, Runner(ok_reply(EMAIL), ok_reply("other@gmail.com")))
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    fi.observe(env.bridge, [ff_tab(url="https://arena.ai/c/9")])
    await fi.drain(env.bridge)
    assert env.pool.get_page("A.Profile1_tab1").label == "other@gmail.com"


@pytest.mark.asyncio
async def test_a_busy_page_is_deferred_not_dropped(env):
    tabs = join(env, ff_tab())
    runner = use(env, Runner())
    env.pool.mark_busy("A.Profile1_tab1", "job-1")
    assert fi.observe(env.bridge, tabs) is False
    env.pool.mark_steady("A.Profile1_tab1")
    assert fi.observe(env.bridge, tabs) is True
    await fi.drain(env.bridge)
    assert len(runner.calls) == 1


# ── overlay reconciliation ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_tab_that_left_the_pool_gets_its_stale_overlay_cleared(env):
    tabs = join(env, ff_tab())
    runner = use(env, Runner())
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    env.pool.remove_page("A.Profile1_tab1")                        # unchecked row, tab still open
    assert fi.observe(env.bridge, tabs) is True
    await fi.drain(env.bridge)
    assert runner.calls[-1][1] == {"no": 0, "name": "", "clear": True}
    assert fi.observe(env.bridge, tabs) is False                    # exactly one clear


@pytest.mark.asyncio
async def test_rejoin_under_a_new_number_redraws_instead_of_clearing(env):
    tabs = join(env, ff_tab())
    runner = use(env, Runner())
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    env.pool.remove_page("A.Profile1_tab1")
    fi.observe(env.bridge, [])                                      # tab closed: nothing to clear
    join(env, ff_tab())                                             # back as worker #2
    fi.observe(env.bridge, tabs)
    await fi.drain(env.bridge)
    assert runner.calls[-1][1]["no"] == 2 and not runner.calls[-1][1]["clear"]
    assert fi.book_of(env.bridge).clears == {}


def test_a_live_drain_lease_blocks_a_second_drain(env):
    tabs = join(env, ff_tab())
    assert fi.observe(env.bridge, tabs) is True
    assert fi.observe(env.bridge, tabs) is False                    # lease held
    env.clock.t += fi.LEASE_SEC + 1
    assert fi.observe(env.bridge, tabs) is True                     # a dead drain frees it


def test_no_pool_no_work(env):
    assert fi.observe(SimpleNamespace(_page_pool=None), []) is False
