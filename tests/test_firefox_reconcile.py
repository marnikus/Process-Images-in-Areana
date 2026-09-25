"""`live/reconcile` + Firefox — one fetch, one pool, both browsers (design D-1/D-5).

Real `Bridge` + real `PagePool` behind a scripted `LiveDeps`: Firefox rows
join the pool through `deps.join_entry`, navigations refresh pooled pages,
the owner's `🦊 Firefox: +a added, −r removed, s steady` line appears only on
events (never per pass), and a dead Chrome endpoint protects Chrome's rows
(D-3) while Firefox keeps the pass alive.
"""

import pytest

from app.browser.page_pool import PagePool, discovered_page_info
from app.core.models import UrlRow
from app.services.live import reconcile as rc
from app.ui.panels import browser_tabs
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit


def chrome_tab(id_, url="https://arena.ai/c/1"):
    return type("Tab", (), {"id": id_, "title": "T", "url": url,
                            "ws_url": f"ws://x/{id_}", "type": "page"})()


def ff_tab(id_="ArenaProfile_tab0", url="https://arena.ai/c/9"):
    return type("FF", (), {"id": id_, "title": "FF Arena", "url": url,
                           "ws_url": "", "type": "page", "browser": "firefox"})()


class Deps:
    """Scripted fetches; `join_entry` really pools the discovered page (D-5)."""

    def __init__(self, bridge, *fetches):
        self.fetches, self.lines, self.joined = list(fetches), [], []
        self.bridge = bridge

    async def fetch_tabs(self):
        item = self.fetches.pop(0) if len(self.fetches) > 1 else self.fetches[0]
        if isinstance(item, Exception):
            raise item
        return item

    async def join_tab(self, ws):
        pass

    async def join_entry(self, tab):
        self.joined.append(tab.id)
        self.bridge._page_pool.add_page(discovered_page_info(tab))

    def commit(self):
        self.bridge._save_arena()

    def log(self, msg, level="info"):
        self.lines.append(msg)

    def as_deps(self):
        return rc.LiveDeps(fetch_tabs=self.fetch_tabs, join_tab=self.join_tab,
                           commit=self.commit, log=self.log, join_entry=self.join_entry)


def env_with(tmp_path, *fetches, urls=None, pool=True):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge.state.urls = list(urls or [])
    env.bridge._page_pool = PagePool() if pool else None
    env.deps = Deps(env.bridge, *fetches)
    return env


async def once(env, source="auto"):
    return await rc.reconcile_once(env.bridge, env.deps.as_deps(), source)


def ff_lines(env):
    return [m for m in env.deps.lines if m.startswith("🦊 Firefox:")]


# ── joins ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_new_matching_firefox_tab_is_added_and_pool_joined_once(tmp_path):
    env = env_with(tmp_path, [ff_tab()])
    report = await once(env)
    assert report.ff_added == 1 and report.ff_joined == 1
    assert env.deps.joined == ["ArenaProfile_tab0"]
    page = env.bridge._page_pool.get_page("ArenaProfile_tab0")
    assert page is not None and page.browser == "firefox" and page.is_free()
    assert any(m.startswith("🦊 Firefox: +1 added, −0 removed, 1 steady")
               for m in ff_lines(env)), env.deps.lines

    again = await once(env)
    assert again.ff_joined == 0 and again.ff_added == 0
    assert len(ff_lines(env)) == 1, "a quiet pass never repeats the line (no 5 s spam)"


@pytest.mark.asyncio
async def test_an_unchecked_row_never_pool_joins_its_tab(tmp_path):
    row = UrlRow.create("https://arena.ai/c/9", enabled=False, tab_id="ArenaProfile_tab0")
    env = env_with(tmp_path, [ff_tab()], urls=[row])
    report = await once(env)
    assert report.ff_joined == 0
    assert env.bridge._page_pool.get_page("ArenaProfile_tab0") is None


@pytest.mark.asyncio
async def test_the_fetch_pattern_gates_the_firefox_join(tmp_path):
    env = env_with(tmp_path, [ff_tab(url="https://other.example/x")])
    report = await once(env)
    assert report.ff_added == 0 and report.ff_joined == 0
    assert env.bridge._page_pool.get_page("ArenaProfile_tab0") is None


@pytest.mark.asyncio
async def test_one_bad_join_never_stops_the_rest_of_the_pass(tmp_path):
    env = env_with(tmp_path, [ff_tab(), ff_tab("ArenaProfile_tab1", "https://arena.ai/c/10")])
    original = env.deps.join_entry

    async def boom(tab):
        if tab.id.endswith("_tab0"):
            raise RuntimeError("window gone")
        await original(tab)
    env.deps.join_entry = boom

    report = await once(env)
    assert report.ff_joined == 1
    assert env.bridge._page_pool.get_page("ArenaProfile_tab1") is not None
    assert any("next pass retries" in m for m in env.deps.lines)


# ── navigation and removal ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_navigation_updates_the_pooled_page_url(tmp_path):
    env = env_with(tmp_path, [ff_tab(url="https://arena.ai/c/9")])
    await once(env)
    navigated = ff_tab(url="https://arena.ai/c/NEW")
    env.deps.fetches = [[navigated]]
    await once(env)
    page = env.bridge._page_pool.get_page("ArenaProfile_tab0")
    assert page.url == "https://arena.ai/c/NEW" and page.title == "FF Arena"


@pytest.mark.asyncio
async def test_a_closed_firefox_tab_removes_its_linked_row_after_the_misses(tmp_path):
    keep = chrome_tab("tz", "https://arena.ai/c/2")
    row = UrlRow.create("https://arena.ai/c/9", enabled=True, tab_id="ArenaProfile_tab0")
    env = env_with(tmp_path, [ff_tab(), keep], urls=[row])
    await once(env)                                   # row survives: live tab
    env.deps.fetches = [[keep]]                       # firefox closed, chrome still answers
    reports = [await once(env) for _ in range(4)]
    assert any(r.ff_removed >= 1 for r in reports)
    assert all(u.tab_id != "ArenaProfile_tab0" for u in env.bridge.state.urls)
    assert any("🦊 Firefox:" in m and "−1 removed" in m for m in ff_lines(env)), env.deps.lines


# ── per-browser outage protection (D-3) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_a_dead_chrome_endpoint_is_a_wait_for_chrome_rows(tmp_path):
    row = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env = env_with(tmp_path, [ff_tab()], urls=[row])
    env.bridge._chrome_scan_down = True   # chrome fetched nothing; firefox answered
    for _ in range(4):
        await once(env)
    assert row in env.bridge.state.urls, "a live browser must not age out Chrome's rows"
    assert any(u.tab_id == "ArenaProfile_tab0" for u in env.bridge.state.urls), \
        "the firefox pass kept working all along"


@pytest.mark.asyncio
async def test_without_protection_the_same_rows_age_out_as_before(tmp_path):
    row = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env = env_with(tmp_path, [ff_tab()], urls=[row])
    env.bridge._chrome_scan_down = False  # chrome really answered: nothing new
    reports = [await once(env) for _ in range(4)]
    assert any(r.removed >= 1 for r in reports), "two misses still remove (hysteresis 2)"
    assert all(u.tab_id != "t1" for u in env.bridge.state.urls)
    assert any(u.tab_id == "ArenaProfile_tab0" for u in env.bridge.state.urls), \
        "only the dead tab's row goes — the live firefox row stays"


# ── the source-level seams ───────────────────────────────────────────────────

def test_reconcile_never_imports_ui_or_browser():
    from pathlib import Path
    src = Path(rc.__file__).read_text(encoding="utf-8")
    assert "from app.browser" not in src and "import app.ui" not in src


def test_the_live_deps_seam_carries_join_entry():
    import inspect
    fields = {f.name for f in rc.LiveDeps.__dataclass_fields__.values()}
    assert "join_entry" in fields
    default = rc.LiveDeps.__dataclass_fields__["join_entry"].default
    assert default is None, "chrome-only constructions stay valid (keyword-safe)"


def test_report_carries_the_firefox_counters():
    r = rc.Report()
    assert (r.ff_added, r.ff_removed, r.ff_joined) == (0, 0, 0)
    assert not r.changed(), "firefox counters never fake a chrome-side change"
