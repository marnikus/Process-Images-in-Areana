"""I-64 · Many tab sources, one reconcile — Firefox rows live like Chrome rows.

The same loop adds, links, joins (by id for Firefox), follows navigation,
ages out closed tabs and logs a Firefox count line. A browser that stays
silent holds its rows AND pages; an empty Chrome answer holds its rows only
(the old "an empty fetch never touches rows"). A typed row is never removed,
only unlinked. Real reconciler + real Bridge; fakes only behind `LiveDeps`.
"""

from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.services import auto_connect as ac
from app.services.live import reconcile as rc
from app.services.live import sources as src
from tests.test_live_reconcile import env_with, tab

pytestmark = pytest.mark.unit

FOX = "9THrgpBc.Profile1_tab1"


def fox(tab_id=FOX, url="https://arena.ai/c/7", title="LMArena"):
    return SimpleNamespace(id=tab_id, url=url, title=title, ws_url="", conn="uivision", type="page")


def row(url, tab_id, typed=False):
    item = UrlRow.create(url, enabled=True, tab_id=tab_id)
    item.typed = typed
    return item


async def passes(env, n=1, source="auto"):
    report = None
    for _ in range(n):
        report = await rc.reconcile_once(env.bridge, env.deps.as_deps(), source)
    return report


def lines(env, needle):
    return [m for m in env.deps.lines if needle in m]


def test_the_join_handle_is_the_socket_for_cdp_and_the_id_for_uivision():
    assert ac.join_handle(tab("C1")) == "ws://127.0.0.1:9222/devtools/page/C1"
    assert ac.join_handle(fox()) == FOX
    assert ac.join_handle(SimpleNamespace(id="C2", ws_url="")) == ""   # an attached CDP tab has no socket


def test_the_listing_answers_the_three_questions():
    listing = src.TabListing([tab("C1")], held_rows={"R"}, held_pages={"P", ""}, answered=True)
    assert src.held_pages(listing) == {"P"} and src.held_rows(listing) == {"R", "P"}
    assert src.live_keys(listing) == {"C1", "R", "P"}
    assert src.answered(src.TabListing([], answered=True)) and not src.answered([])
    assert src.held_rows([tab("C1")]) == frozenset() and src.held_pages(None) == frozenset()
    assert src.keys_of({FOX, "C1", ""}, ["firefox"]) == {FOX}


def test_the_firefox_line_speaks_on_change_or_when_asked():
    assert src.firefox_line(set(), set(), True) == ""                    # no Firefox rows at all
    assert src.firefox_line({FOX}, {FOX}, False) == ""                   # nothing changed, auto pass
    assert src.firefox_line({FOX}, {FOX}, True) == \
        "🦊 Reconcile: +0 firefox added, −0 firefox removed, 1 firefox steady"
    assert src.firefox_line({FOX}, {"P_tab2"}, False) == \
        "🦊 Reconcile: +1 firefox added, −1 firefox removed, 0 firefox steady"
    assert src.firefox_ids([row("u", FOX), row("v", "C1"), row("w", "")]) == {FOX}


@pytest.mark.asyncio
async def test_a_firefox_tab_gets_a_row_and_joins_by_id(tmp_path):
    env = env_with(tmp_path, src.TabListing([tab("C1"), fox()], answered=True))
    report = await passes(env)
    assert report.added == 2
    assert env.deps.joined == [tab("C1").ws_url, FOX]
    assert {u.tab_id for u in env.bridge.state.urls} == {"C1", FOX}
    assert lines(env, "🦊 Reconcile:") == ["🦊 Reconcile: +1 firefox added, −0 firefox removed, 0 firefox steady"]


@pytest.mark.asyncio
async def test_a_silent_chrome_never_ages_its_rows_while_firefox_answers(tmp_path):
    chrome_row = row("https://arena.ai/c/1", "C1")
    held = src.TabListing([fox()], held_rows={"C1"}, held_pages={"C1"}, answered=True)
    env = env_with(tmp_path, held, urls=[chrome_row])
    await passes(env, 3)
    assert chrome_row in env.bridge.state.urls
    bare = env_with(tmp_path / "bare", src.TabListing([fox()], answered=True), urls=[row("https://arena.ai/c/1", "C1")])
    await passes(bare, 3)
    assert [u.tab_id for u in bare.bridge.state.urls] == [FOX]          # without the hold it ages out


@pytest.mark.asyncio
async def test_an_empty_chrome_answer_keeps_rows_but_marks_its_pages_stale(tmp_path):
    env = env_with(tmp_path, src.TabListing([fox()], held_rows={"C1"}, answered=True),
                   urls=[row("https://arena.ai/c/1", "C1")])
    pool = env.bridge._page_pool = PagePool()
    pool.add_page(PageInfo(tab_id="C1", ws_url="ws://c1", url="https://arena.ai/c/1"))
    await passes(env)
    assert any(u.tab_id == "C1" for u in env.bridge.state.urls)
    assert pool.get_page("C1").is_connected is False
    env.deps.fetches = [src.TabListing([fox()], held_rows={"C1"}, held_pages={"C1"}, answered=True)]
    await passes(env)
    assert pool.get_page("C1").is_connected is True                     # silent → held connected


@pytest.mark.asyncio
async def test_a_linked_auto_row_follows_its_tab_to_a_new_matching_url(tmp_path):
    moved = row("https://arena.ai/c/1", FOX)
    strayed = row("https://arena.ai/c/2", "C2")
    typed = row("https://arena.ai/c/3", "C3", typed=True)
    listing = src.TabListing([fox(url="https://arena.ai/c/9"), tab("C2", "https://google.com/"),
                              tab("C3", "https://arena.ai/c/33")], answered=True)
    env = env_with(tmp_path, listing, urls=[moved, strayed, typed])
    await passes(env)
    assert moved.url == "https://arena.ai/c/9"
    assert strayed.url == "https://arena.ai/c/2" and typed.url == "https://arena.ai/c/3"
    assert lines(env, "🔀 URL followed") == [
        f"🔀 URL followed https://arena.ai/c/1 → https://arena.ai/c/9 (tab {FOX}) — the tab navigated"]
    assert env.deps.commits == 1                                        # the in-place change is saved


@pytest.mark.asyncio
async def test_a_typed_row_whose_tab_is_gone_is_unlinked_never_removed(tmp_path):
    typed = row("https://arena.ai/c/2", "P.x_tab2", typed=True)
    auto = row("https://arena.ai/c/3", "P.x_tab3")
    env = env_with(tmp_path, src.TabListing([], answered=True), urls=[typed, auto])
    await passes(env, 2)
    assert env.bridge.state.urls == [typed] and typed.tab_id == ""
    assert lines(env, "🔗 Typed URL kept") == [
        "🔗 Typed URL kept https://arena.ai/c/2 — tab closed (2 reconciles); unlinked from tab P.x_tab2"]
    assert lines(env, "🦊 Reconcile:")[-1].startswith("🦊 Reconcile: +0 firefox added, −2 firefox removed")


@pytest.mark.asyncio
async def test_a_manual_reparse_keeps_typed_and_silent_rows(tmp_path):
    typed = row("https://arena.ai/c/2", "P.x_tab2", typed=True)
    chrome_row = row("https://arena.ai/c/1", "C1")
    auto = row("https://arena.ai/c/7", FOX)
    listing = src.TabListing([fox()], held_rows={"C1"}, held_pages={"C1"}, answered=True)
    env = env_with(tmp_path, listing, urls=[typed, chrome_row, auto])
    await passes(env, source="manual")
    kept = env.bridge.state.urls
    assert typed in kept and chrome_row in kept and auto not in kept   # the auto row was rebuilt
    assert [u.tab_id for u in kept if u.tab_id == FOX] == [FOX]
    assert lines(env, "🦊 Reconcile:")                                  # a manual pass always answers


@pytest.mark.asyncio
async def test_pooled_firefox_pages_take_their_tabs_title_and_url(tmp_path):
    env = env_with(tmp_path, src.TabListing([fox(title="Chat 9", url="https://arena.ai/c/9"), tab("C1")],
                                            answered=True), urls=[row("https://arena.ai/c/7", FOX)])
    pool = env.bridge._page_pool = PagePool()
    pool.add_page(PageInfo(tab_id=FOX, title="LMArena", url="https://arena.ai/c/7", browser="firefox"))
    pool.add_page(PageInfo(tab_id="C1", ws_url="ws://c1", title="Old", url="https://arena.ai/old"))
    await passes(env)
    assert (pool.get_page(FOX).title, pool.get_page(FOX).url) == ("Chat 9", "https://arena.ai/c/9")
    assert pool.get_page("C1").title == "Old"                            # Chrome's own fields untouched
    assert src.refresh_firefox_pages(None, [fox()]) == 0


@pytest.mark.asyncio
async def test_a_tab_without_a_join_handle_gets_a_row_but_no_join(tmp_path):
    attached = SimpleNamespace(id="C9", url="https://arena.ai/c/9", title="T", ws_url="", type="page")
    env = env_with(tmp_path, src.TabListing([attached], answered=True))
    report = await passes(env)
    assert report.added == 1 and report.joined == 0 and env.deps.joined == []   # "" is skipped, never joined


@pytest.mark.asyncio
async def test_duplicate_rows_for_one_tab_are_repaired_with_a_line(tmp_path):
    env = env_with(tmp_path, src.TabListing([tab("C1")], answered=True),
                   urls=[row("https://arena.ai/c/1", "C1"), row("https://arena.ai/c/1b", "C1")])
    await passes(env)
    assert [u.tab_id for u in env.bridge.state.urls] == ["C1"]
    assert lines(env, "extra row(s)") == ["🤖 Reconcile: removed 1 extra row(s) — their tab already has a row"]
