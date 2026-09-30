"""I-79 — "Start new chat as new tab": the fresh tab lives in the job tab's own profile.

The fake world models what the handover must believe: **one browser per endpoint**, every tab with
its own browser context, and the ways a tab really appears in it — `Target.createTarget` honouring
a context, the same call silently landing in the default profile (the reported A2 bug), and the
page's own `window.open` (profile-locked). Real PagePool, real AliasBook, real UrlRows, real JS
payload for the page opener; the browser and the CDP socket are fakes. Design:
docs/archive/2026-09-29-new-chat-new-tab-profile-truth/design.md.
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from app.browser.cdp import browser_targets as bt
from app.browser.cdp.tabs import TabInfo
from app.browser.page_pool import PagePool, retarget_page
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.core.tab_alias import AliasBook
from app.services import new_tab, new_tab_setting
from app.services.cooldown_service import FinishCtx

pytestmark = pytest.mark.unit

NEW_URL = "https://arena.ai/image/direct?model_a=max"
DEFAULT_CTX = ""            # Chrome's default profile: TargetInfo carries no browserContextId
PROFILE_2 = "CTX-P2"
_POPUP_URL_RE = re.compile(r'const url = ("(?:[^"\\]|\\.)*")')


# ── the browser ─────────────────────────────────────────────────────────────

class FakeBrowser:
    """One Chrome at one endpoint: its targets, their profile contexts and what it allows."""

    def __init__(self, host="127.0.0.1", port=9333):
        self.host, self.port = host, port
        self.tabs: dict[str, dict] = {}
        self.owners: dict[str, str] = {}      # context id → the account signed in there
        self.tab_owners: dict[str, str] = {}  # per-tab override (a lying page)
        self.seq = 0
        self.silent = False          # Target.getTargets answers nothing: the profile is unprovable
        self.refuse_ctx = False      # a regular profile: createTarget{browserContextId} is refused
        self.reuse_default = False   # createTarget lands in the default profile regardless (A2)
        self.creatable_contexts = None   # Target.getBrowserContexts; None = browser cannot answer
        self.stray_on_popup = ""     # a foreign fresh tab that appears together with our popup
        self.popup_allowed = True
        self.close_ignored = False
        self.wrong_owner_after_open = False
        self.calls: list[tuple] = []
        self.opened: list[str] = []
        self.closed: list[str] = []

    def add(self, tab_id, url="https://arena.ai/c/1", ctx=DEFAULT_CTX, opener="", owner=""):
        row = {"targetId": tab_id, "type": "page", "title": "", "url": url, "attached": False}
        if ctx:
            row["browserContextId"] = ctx
        if opener:
            row["openerId"] = opener
        self.tabs[tab_id] = row
        if owner:
            self.tab_owners[tab_id] = owner      # a label this tab already shows
        return tab_id

    def infos(self) -> list[dict]:
        return [dict(row) for row in self.tabs.values()]

    def ctx_of(self, tab_id: str) -> str:
        return self.tabs[tab_id].get("browserContextId", DEFAULT_CTX)

    def owner_of(self, tab_id: str) -> str:
        if tab_id in self.tab_owners:
            return self.tab_owners[tab_id]
        return self.owners.get(self.ctx_of(tab_id), "")

    def _new_id(self, prefix="NEW"):
        self.seq += 1
        return f"{prefix}{self.seq}"

    def create(self, url, ctx):
        self.calls.append(("create", url, ctx))
        if ctx and self.refuse_ctx:
            return "", f"Failed to find browser context with id {ctx}"
        landed = DEFAULT_CTX if (self.reuse_default or not ctx) else ctx
        return self.add(self._new_id(), url, landed), ""

    def popup(self, opener_id, url):
        self.calls.append(("popup", opener_id, url))
        if opener_id not in self.tabs:
            return "", "the page is gone"
        if not self.popup_allowed:
            return "", "window.open returned null (popup blocked)"
        if self.stray_on_popup:
            self.add(self.stray_on_popup, url, DEFAULT_CTX)   # another surface's tab, sorts first
        tid = self.add(self._new_id("POP"), url, self.ctx_of(opener_id), opener=opener_id)
        if self.wrong_owner_after_open:
            self.tab_owners[tid] = "other@example.com"
        return tid, ""

    def close(self, tab_id):
        self.calls.append(("close", tab_id))
        if not self.close_ignored:
            self.tabs.pop(tab_id, None)
            self.closed.append(tab_id)
        return True, ""

    def listing(self, host, port, timeout=3.0):
        pages = [t for t in self.tabs.values() if t["type"] == "page"]
        return ([TabInfo(t["targetId"], t.get("title", ""), t["url"],
                         f"ws://{host}:{port}/devtools/page/{t['targetId']}") for t in pages],
                "", [f"http://{host}:{port}/json/list"])


class FakeProbe:
    """`BrowserTargets`' contract over one `FakeBrowser` (the `dial` seam's result)."""

    def __init__(self, browser):
        self.browser, self.closed = browser, False

    async def targets(self):
        if self.browser.silent:
            return [], "the browser did not answer Target.getTargets"
        return self.browser.infos(), ""

    async def get_browser_contexts(self):
        if self.browser.creatable_contexts is None:
            return set(), "the browser did not answer Target.getBrowserContexts"
        return set(self.browser.creatable_contexts), ""

    async def create(self, url, context_id):
        return self.browser.create(url, context_id)

    async def close(self, tab_id):
        return self.browser.close(tab_id)

    async def aclose(self):
        self.closed = True


class FakePageClient:
    """A CDP client on one tab: `connect` follows the move, `evaluate`/`send` answer the page probes."""

    def __init__(self, browser, tab_id, owner_visible=True, host=None, port=None):
        self._host = host or browser.host
        self._port = port or browser.port
        self.browser, self.owner_visible = browser, owner_visible
        self._current_tab_id = tab_id
        self.moves: list[str] = []

    async def connect(self, ws_url):
        self.moves.append(ws_url)
        self._current_tab_id = ws_url.rsplit("/", 1)[-1]
        return True

    def _answer(self) -> str:
        return self.browser.owner_of(self._current_tab_id) if self.owner_visible else ""

    async def evaluate(self, expression, await_promise=True, timeout=30.0):
        return {"email": self._answer()}

    async def send(self, method, params=None, timeout=30):
        expr = (params or {}).get("expression", "")
        if "window.open" in expr:                       # the real popup payload, page-side
            url = json.loads(_POPUP_URL_RE.search(expr).group(1))
            tid, err = self.browser.popup(self._current_tab_id, url)
            value = {"ok": True} if tid else {"ok": False, "error": err}
            return {"id": 1, "result": {"result": {"type": "object", "value": value}}}
        return {"id": 1, "result": {"result": {"type": "object", "value": {"email": self._answer()}}}}


# ── the world ───────────────────────────────────────────────────────────────

def _pool_with(*tab_ids, host="127.0.0.1", port=9333):
    pool = PagePool(alias_book=AliasBook())
    for tid in tab_ids:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://{host}:{port}/devtools/page/{tid}",
                               url="https://arena.ai/c/1"))
    return pool


async def _always_ready(reset_ctx):
    return True, "new chat ready"


async def _always_new(client):
    return True, "new chat"


async def _ready(reset_ctx):
    """The reset's readiness check always passes in the fake world."""
    return True, "new chat ready"


async def _is_new_chat(client):
    return True, "new chat"


def _fake_dial(world, browser, host, port):
    """A dial that knows exactly one endpoint — any other address is unreachable."""
    async def dial(h, p, timeout_sec=5.0):
        world.dialed.append((h, p))
        if (h, p) != (host, port):
            return None, f"no browser at {h}:{p}"
        probe = FakeProbe(browser)
        world.probes.append(probe)
        return probe, ""
    return dial


def _world(monkeypatch, *, old_ctx=DEFAULT_CTX, other_ctx=DEFAULT_CTX, host="127.0.0.1", port=9333,
           old_owner="anton@example.com", other_owner="mxxy@example.com", owner_visible=True):
    """The pool, the bridge and the job tab (OLD) + a second tab (OTHER) at one endpoint."""
    browser = FakeBrowser(host, port)
    browser.add("OLD", "https://arena.ai/c/1", old_ctx, owner=old_owner)
    browser.add("OTHER", "https://arena.ai/c/2", other_ctx, owner=other_owner)
    browser.owners = {old_ctx: old_owner}     # a tab opened into the job's profile keeps its account
    world = SimpleNamespace(browser=browser, dialed=[], probes=[], logs=[], saved=[])
    world.owner_visible = owner_visible
    monkeypatch.setattr(bt, "dial", _fake_dial(world, browser, host, port))
    monkeypatch.setattr(new_tab, "wait_new_chat_ready", _ready)
    monkeypatch.setattr(new_tab, "read_chat_page", _is_new_chat)
    pool = _world_pool(browser, host=host, port=port, old_owner=old_owner, owner_visible=owner_visible)
    rows = [UrlRow(id="r1", url="https://arena.ai/c/1", enabled=True, tab_id="OLD"),
            UrlRow(id="r2", url="https://arena.ai/c/2", enabled=True, tab_id="OTHER")]
    bridge = _world_bridge(world, rows, pool.get_clients("OLD")[0])
    world.pool, world.rows, world.bridge = pool, rows, bridge
    world.clients = SimpleNamespace(job=bridge.cdp, pooled=pool.get_clients("OLD")[0], home=bridge.cdp)
    world.ctx = FinishCtx(pool=pool, bridge=bridge, tab_id="OLD", ctrl=object(), client=bridge.cdp)
    return world


def _world_pool(browser, *, host, port, old_owner, owner_visible):
    """The real PagePool with the job tab (client registered) and a second tab."""
    pool = _pool_with("OLD", "OTHER", host=host, port=port)
    pool.get_page("OLD").jobs_completed = 3
    pool.get_page("OLD").owner = old_owner        # the pool's label the handover must keep
    job_client = FakePageClient(browser, "OLD", owner_visible=owner_visible)
    pool.register_client("OLD", FakePageClient(browser, "OLD", owner_visible=owner_visible), object())
    browser.job_client = job_client               # the ctx's own client (same tab)
    return pool


def _world_bridge(world, rows, pooled_client):
    """A bridge with the pool hooks the handover calls, logging into `world`."""
    return SimpleNamespace(
        state=SimpleNamespace(urls=rows), _auto_scan_running=False, cdp=world.browser.job_client,
        _cancel_requested=False,
        _log=lambda m, l="info": world.logs.append((l, m)),
        _save_arena=lambda: world.saved.append("arena"),
        _persist_cooldowns=lambda: world.saved.append("cooldowns"),
        _emit_pool_status=lambda: None)


def _run(world, url=NEW_URL):
    return asyncio.run(new_tab.handover(world.ctx, url, timeout_sec=5))


def _mutations(world) -> list[tuple]:
    """Everything that changed the browser's tab set."""
    return [c for c in world.browser.calls if c[0] in ("create", "popup", "close")]


def _text(world) -> str:
    return " | ".join(m for _, m in world.logs)


# ── the tab's own profile is the truth (v5) ─────────────────────────────────

def test_the_new_tab_opens_in_the_job_tabs_own_profile(monkeypatch):
    """A regular Chrome profile refuses CDP creation — the job tab's own page opens the tab."""
    w = _world(monkeypatch, old_ctx=PROFILE_2, other_ctx=DEFAULT_CTX)
    w.browser.refuse_ctx = True
    ok, why = _run(w)
    assert ok, why
    new_id = w.ctx.tab_id
    assert new_id != "OLD" and w.browser.ctx_of(new_id) == PROFILE_2
    assert w.browser.tabs["OTHER"]["targetId"] == "OTHER"        # the other profile untouched
    assert "OLD" not in w.browser.tabs                            # the old tab of that profile closed
    assert w.pool.get_page("OLD") is None and w.pool.get_page(new_id).jobs_completed == 3
    assert (w.rows[0].tab_id, w.rows[0].url, w.rows[0].enabled) == (new_id, NEW_URL, True)
    assert w.rows[1].tab_id == "OTHER"
    assert w.pool.get_page(new_id).ws_url == f"ws://127.0.0.1:9333/devtools/page/{new_id}"
    for client in (w.clients.job, w.clients.pooled, w.clients.home):   # every holder moved
        assert client._current_tab_id == new_id
    assert w.dialed == [("127.0.0.1", 9333)] and w.probes[0].closed is True
    assert w.bridge._auto_scan_running is False


def test_the_cdp_creation_is_tried_first_in_the_job_tabs_context(monkeypatch):
    """A context Chrome can create into (an OTR/devtools context) needs no page involvement."""
    w = _world(monkeypatch, old_ctx=PROFILE_2, other_ctx=DEFAULT_CTX)
    ok, why = _run(w)
    assert ok, why
    assert [c for c in w.browser.calls if c[0] == "create"] == [("create", NEW_URL, PROFILE_2)]
    assert [c for c in w.browser.calls if c[0] == "popup"] == []
    assert w.browser.ctx_of(w.ctx.tab_id) == PROFILE_2


def test_a_wrong_profile_tab_is_closed_again_and_the_handover_refused(monkeypatch):
    """The reported A2: the browser ignores the context and opens in the default profile."""
    w = _world(monkeypatch, old_ctx=PROFILE_2, other_ctx=DEFAULT_CTX)
    w.browser.reuse_default = True
    w.browser.popup_allowed = False
    ok, why = _run(w)
    assert not ok and "profile" in why.lower()
    assert w.ctx.tab_id == "OLD" and "OLD" in w.browser.tabs
    assert w.pool.get_page("OLD") is not None and w.rows[0].tab_id == "OLD"
    foreign = [t for t in w.browser.tabs if w.browser.ctx_of(t) != PROFILE_2]
    assert foreign == ["OTHER"]                       # the wrong-profile tab was closed again
    assert [c for c in w.browser.calls if c[0] == "close"] == [("close", "NEW1")]
    assert w.clients.job._current_tab_id == "OLD"     # no client was left on the foreign tab


def test_an_unanswered_target_list_is_no_handover(monkeypatch):
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.silent = True
    ok, why = _run(w)
    assert not ok and "Target.getTargets" in why
    assert _mutations(w) == [] and w.ctx.tab_id == "OLD"


def test_a_job_tab_that_is_not_in_its_own_browser_is_no_handover(monkeypatch):
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.tabs.pop("OLD")
    ok, why = _run(w)
    assert not ok and "browser" in why.lower()
    assert _mutations(w) == [] and w.ctx.tab_id == "OLD"


def test_a_blocked_popup_refuses_the_handover_instead_of_opening_elsewhere(monkeypatch):
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True
    w.browser.popup_allowed = False
    ok, why = _run(w)
    assert not ok and "popup" in why.lower()
    assert w.browser.tabs["OLD"]["targetId"] == "OLD" and w.ctx.tab_id == "OLD"
    assert w.rows[0].tab_id == "OLD" and w.pool.get_page("OLD").jobs_completed == 3


def test_the_endpoint_is_the_job_tabs_own_socket_not_the_clients(monkeypatch):
    """The global and job clients may sit on another profile's endpoint — they decide nothing."""
    w = _world(monkeypatch, port=9334)
    for client in (w.clients.job, w.clients.home, w.ctx.client):
        client._host, client._port = "127.0.0.1", 9222
    ok, why = _run(w)
    assert ok, why
    assert w.dialed == [("127.0.0.1", 9334)]
    assert w.browser.ctx_of(w.ctx.tab_id) == DEFAULT_CTX


def test_the_popup_runs_on_a_client_that_sits_on_the_job_tab(monkeypatch):
    """A drifted global client must not be the page that opens the tab (its profile would win)."""
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True
    w.clients.job._current_tab_id = "OTHER"       # the job's own client points elsewhere
    ok, why = _run(w)
    assert ok, why
    assert w.browser.ctx_of(w.ctx.tab_id) == PROFILE_2
    assert w.pool.get_page(w.ctx.tab_id) is not None


def test_no_client_on_the_job_tab_and_a_refusing_browser_refuses(monkeypatch):
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True
    for client in (w.clients.job, w.clients.pooled, w.clients.home):
        client._current_tab_id = "OTHER"
    ok, why = _run(w)
    assert not ok and "job tab" in why
    assert w.ctx.tab_id == "OLD" and w.browser.closed == [] and "OLD" in w.browser.tabs


def test_a_tab_whose_socket_is_unreadable_is_no_handover(monkeypatch):
    w = _world(monkeypatch)
    w.pool.get_page("OLD").ws_url = ""
    ok, why = _run(w)
    assert not ok and "socket" in why.lower()
    assert w.dialed == [] and _mutations(w) == []


def test_the_profile_counts_in_the_log_come_from_the_browser_truth(monkeypatch):
    w = _world(monkeypatch, old_ctx=PROFILE_2, other_ctx=DEFAULT_CTX)
    w.browser.add("P2B", "https://arena.ai/c/3", PROFILE_2)
    ok, _ = _run(w)
    assert ok
    text = _text(w)
    assert "this profile: 2" in text and "all contexts: 3" in text
    assert PROFILE_2 in text


# ── v6: the opener knows its place (owner report 2026-09-30, "bug appear again") ──────────

def test_a_regular_profile_handover_never_flashes_a_tab_into_the_default_profile(monkeypatch):
    """The owner's Chrome accepts the create but lands it in the default profile — never fire it.

    `Target.getBrowserContexts` says the job profile is not creatable, so the page opener is the
    first and only route: no default-profile tab is ever opened (and closed) in profile 1's window.
    """
    w = _world(monkeypatch, old_ctx=PROFILE_2, other_ctx=DEFAULT_CTX)
    w.browser.creatable_contexts = set()      # the browser answers: nothing is creatable
    w.browser.reuse_default = True            # ...and a fired create would silently land default
    ok, why = _run(w)
    assert ok, why
    assert [c for c in w.browser.calls if c[0] == "create"] == []
    assert w.browser.ctx_of(w.ctx.tab_id) == PROFILE_2        # the worker is in its own profile
    assert w.browser.closed == ["OLD"]                        # only the old tab was ever closed


def test_a_stray_tab_in_the_popup_diff_is_left_alone(monkeypatch):
    """A foreign fresh tab that sorts before ours is never adopted and never closed (v6 R1)."""
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True
    w.browser.stray_on_popup = "A-STRAY"      # appears with our popup, opener is somebody else
    ok, why = _run(w)
    assert ok, why
    assert w.browser.ctx_of(w.ctx.tab_id) == PROFILE_2
    assert "A-STRAY" in w.browser.tabs
    assert w.browser.closed == ["OLD"]


# ── I-79 kept: proof, close, rollback ──────────────────────────────────────

def test_a_new_tab_that_is_not_a_new_chat_rolls_back(monkeypatch):
    w = _world(monkeypatch)
    async def not_new(client):
        return False, "an old chat"
    monkeypatch.setattr(new_tab, "read_chat_page", not_new)
    ok, why = _run(w)
    assert not ok and "an old chat" in why
    assert w.ctx.tab_id == "OLD" and "OLD" in w.browser.tabs
    assert w.pool.get_page("OLD") is not None and w.rows[0].tab_id == "OLD"
    assert [c for c in w.browser.calls if c[0] == "close"] == [("close", "NEW1")]  # closed again
    for client in (w.clients.job, w.clients.pooled, w.clients.home):
        assert client._current_tab_id == "OLD"                                      # all home
    assert w.bridge._auto_scan_running is False


def test_a_new_tab_that_never_gets_ready_rolls_back(monkeypatch):
    w = _world(monkeypatch)
    async def never(reset_ctx):
        return False, "timeout waiting for new chat"
    monkeypatch.setattr(new_tab, "wait_new_chat_ready", never)
    ok, why = _run(w)
    assert not ok and "timeout" in why and w.ctx.tab_id == "OLD"
    assert [c for c in w.browser.calls if c[0] == "close"] == [("close", "NEW1")]


def test_an_owner_mismatch_rolls_back(monkeypatch):
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True
    w.browser.wrong_owner_after_open = True
    ok, why = _run(w)
    assert not ok and "wrong profile" in why
    assert w.ctx.tab_id == "OLD" and w.rows[0].tab_id == "OLD"
    assert "OLD" in w.browser.tabs


def test_an_empty_owner_answer_does_not_block_a_proven_profile(monkeypatch):
    w = _world(monkeypatch, old_ctx=PROFILE_2, owner_visible=False)
    w.browser.refuse_ctx = True
    ok, why = _run(w)
    assert ok, why
    assert w.browser.ctx_of(w.ctx.tab_id) == PROFILE_2
    assert "owner" in _text(w).lower()                 # it says the account stayed unknown


def test_the_same_new_chat_url_still_closes_the_old_tab(monkeypatch):
    w = _world(monkeypatch)
    w.pool.get_page("OLD").url = NEW_URL
    w.rows[0].url = NEW_URL
    ok, _ = _run(w)
    assert ok and [c for c in w.browser.calls if c[0] == "close"] == [("close", "OLD")]
    assert "OLD" not in w.browser.tabs and any("same" in m.lower() for _, m in w.logs)


def test_an_old_tab_that_stays_open_is_reported_loudly(monkeypatch):
    w = _world(monkeypatch)
    w.browser.close_ignored = True
    ok, _ = _run(w)
    assert ok and w.ctx.tab_id != "OLD"                       # the job moved; only the close failed
    assert [c for c in w.browser.calls if c[0] == "close"] == [("close", "OLD"), ("close", "OLD")]
    assert any(level == "error" and "still open" in m for level, m in w.logs)


def test_a_browser_that_cannot_be_dialled_refuses(monkeypatch):
    w = _world(monkeypatch)
    monkeypatch.setattr(bt, "dial", lambda h, p, timeout_sec=5.0: _none_dial(h, p))
    ok, why = _run(w)
    assert not ok and "not reachable" in why
    assert _mutations(w) == [] and w.ctx.tab_id == "OLD"


async def _none_dial(host, port):
    return None, f"no browser at {host}:{port}"


def test_a_client_that_cannot_follow_the_move_rolls_back(monkeypatch):
    w = _world(monkeypatch)

    async def refuse(ws_url):
        return False
    w.clients.home.connect = refuse
    ok, why = _run(w)
    assert not ok and "connect" in why
    assert "OLD" in w.browser.tabs and w.browser.closed == ["NEW1"]
    assert w.rows[0].tab_id == "OLD" and w.pool.get_page("OLD") is not None
    assert w.bridge._auto_scan_running is False


def test_an_unreadable_pattern_falls_back_to_arena(monkeypatch):
    w = _world(monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("no config")
    w.bridge.config = SimpleNamespace(get_state=boom)
    ok, why = _run(w)
    assert ok, why
    assert "arena.ai" in _text(w)


def test_the_pattern_fallback_comes_from_the_one_home(monkeypatch):
    """The default is `reconcile_rows.DEFAULT_PATTERN`, not a literal in this module (audit #4 N3)."""
    w = _world(monkeypatch)
    monkeypatch.setattr(new_tab, "URL_PATTERN_DEFAULT", "example.test")

    def boom(*_a, **_k):
        raise RuntimeError("no config")
    w.bridge.config = SimpleNamespace(get_state=boom)
    ok, why = _run(w)
    assert ok, why
    assert "tabs matching 'example.test'" in _text(w)


def test_the_pattern_default_has_one_home():
    """The key, its default and the session entry are the same object (audit #4 N3)."""
    from app.persistence import config_manager as cm
    from app.services.live import reconcile_rows
    assert (reconcile_rows.DEFAULT_PATTERN == cm.URL_PATTERN_DEFAULT
            == cm.DEFAULT_SESSION[cm.URL_PATTERN_KEY] == "arena.ai")


def test_the_pattern_key_is_the_shared_one(monkeypatch):
    """`_get_pattern` reads the shared key name — the same one the session default uses."""
    w = _world(monkeypatch)
    seen: list = []

    def get_state(key, default=None):
        seen.append(key)
        return "arena.ai"
    w.bridge.config = SimpleNamespace(get_state=get_state)
    ok, _why = _run(w)
    assert ok and new_tab.URL_PATTERN_KEY in seen


def test_a_raising_owner_probe_does_not_block_a_proven_profile(monkeypatch):
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True

    async def boom(expression, await_promise=True, timeout=30.0):
        raise RuntimeError("evaluate failed")
    for client in (w.clients.job, w.clients.pooled, w.clients.home):
        client.evaluate = boom
    ok, why = _run(w)
    assert ok, why and w.browser.ctx_of(w.ctx.tab_id) == PROFILE_2


def test_a_tab_without_an_owner_label_skips_the_owner_probe(monkeypatch):
    w = _world(monkeypatch)
    w.pool.get_page("OLD").owner = ""
    ok, why = _run(w)
    assert ok, why
    assert "owner=unknown" in _text(w)
    assert w.browser.ctx_of(w.ctx.tab_id) == DEFAULT_CTX


def test_a_running_reconcile_pass_means_no_handover(monkeypatch):
    w = _world(monkeypatch)
    w.bridge._auto_scan_running = True
    monkeypatch.setattr(new_tab, "_RECONCILE_WAIT_SEC", 0.05)
    ok, why = _run(w)
    assert not ok and "reconcile" in why and w.dialed == []
    assert w.bridge._auto_scan_running is True                # not ours to release


def test_a_tab_not_in_the_pool_means_no_handover(monkeypatch):
    w = _world(monkeypatch)
    w.ctx.tab_id = "GONE"
    ok, _ = _run(w)
    assert not ok and w.dialed == []


# ── the worker move (unchanged I-79 behaviour) ──────────────────────────────

def test_retarget_page_keeps_the_worker_under_the_new_key_in_pool_order():
    pool = _pool_with("A", "OLD", "B")
    page = pool.get_page("OLD")
    page.cooldown_until, page.jobs_completed, page.captcha_count = 99.0, 7, 2
    number, worker = page.alias_no, page.worker_no
    client, ctrl = object(), object()
    pool.register_client("OLD", client, ctrl)
    assert retarget_page(pool, "OLD", TabInfo("NEW", "t", NEW_URL, "ws://h:9/devtools/page/NEW"))
    moved = pool.get_page("NEW")
    assert pool.get_page("OLD") is None and moved is page
    assert (moved.tab_id, moved.ws_url, moved.url) == ("NEW", "ws://h:9/devtools/page/NEW", NEW_URL)
    assert (moved.cooldown_until, moved.jobs_completed, moved.captcha_count) == (99.0, 7, 2)
    assert (moved.alias_no, moved.worker_no) == (number, worker)
    assert pool.get_clients("NEW") == (client, ctrl) and pool.get_clients("OLD") == (None, None)
    assert [p["tab_id"] for p in pool.status_snapshot()["pages"]] == ["A", "NEW", "B"]


def test_retarget_page_of_a_tab_not_in_the_pool_is_false():
    assert retarget_page(_pool_with("A"), "OLD", TabInfo("NEW", "", NEW_URL, "ws://x")) is False


def test_alias_book_adopt_moves_the_number_and_owner_to_the_new_tab():
    book = AliasBook()
    no = book.no_for("OLD")
    book.remember("OLD", "user@example.com")
    book.adopt("NEW", "OLD")
    assert book.no_for("NEW") == no and book.owner_for("NEW") == "user@example.com"
    assert "OLD" not in book.as_dict()


def test_alias_book_adopt_of_an_unknown_tab_changes_nothing():
    book = AliasBook()
    book.adopt("NEW", "NOPE")
    assert len(book) == 0


# ── the post-job seam ───────────────────────────────────────────────────────

def _seam(monkeypatch, *, enabled, handover_result=(True, "moved")):
    from app.services import cooldown_service as cs
    calls = []

    async def fake_handover(ctx, url, timeout_sec):
        calls.append(("handover", url))
        return handover_result

    async def fake_reset(reset_ctx):
        calls.append(("in-place", ""))
        return True, "new chat ready"
    monkeypatch.setattr(new_tab, "handover", fake_handover)
    monkeypatch.setattr(cs, "reset_to_new_chat", fake_reset)
    state = {new_tab_setting.SETTING_KEY: enabled, new_tab_setting.URL_KEY: NEW_URL}
    bridge = SimpleNamespace(config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
                             _cancel_requested=False, _log=lambda *a, **k: None)
    ctx = FinishCtx(pool=None, bridge=bridge, tab_id="OLD", ctrl=object(), client=object())
    return cs, ctx, calls


def test_setting_off_keeps_the_in_place_new_chat(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=False)
    assert asyncio.run(cs._best_effort_reset(ctx, 5))[0]
    assert calls == [("in-place", "")]


def test_setting_on_uses_the_new_tab(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=True)
    assert asyncio.run(cs._best_effort_reset(ctx, 5)) == (True, "moved")
    assert calls == [("handover", NEW_URL)]


def test_a_refused_handover_falls_back_to_the_in_place_new_chat(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=True, handover_result=(False, "another profile"))
    assert asyncio.run(cs._best_effort_reset(ctx, 5))[0]
    assert calls == [("handover", NEW_URL), ("in-place", "")]


def test_firefox_lane_never_opens_tabs(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=True)

    async def lane():
        return True, "firefox new chat"
    ctx.lane_reset = lane
    assert asyncio.run(cs._best_effort_reset(ctx, 5)) == (True, "firefox new chat")
    assert calls == []


def test_a_cancelled_run_keeps_the_fast_in_place_reset(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=True)
    monkeypatch.setattr(cs, "_is_cancelled", lambda bridge: True)
    asyncio.run(cs._best_effort_reset(ctx, 5))
    assert calls == [("in-place", "")]


# ── the finished job is never broken by our own side effects ────────────────

def test_a_log_sink_that_raises_never_breaks_the_finished_job(monkeypatch):
    """The handover reports through the bridge; a dead log sink must not fail the job."""
    w = _world(monkeypatch)

    def boom(_message, _level="info"):
        raise RuntimeError("log sink gone")
    w.bridge._log = boom
    ok, why = _run(w)
    assert ok, why and w.ctx.tab_id != "OLD" and w.browser.closed == ["OLD"]


def test_a_save_that_raises_never_breaks_the_finished_job(monkeypatch):
    """`_save_arena`/`_persist_cooldowns` are the bridge's to fail; the move stays done."""
    w = _world(monkeypatch)

    def boom():
        raise RuntimeError("disk full")
    w.bridge._save_arena = boom
    w.bridge._persist_cooldowns = boom
    ok, why = _run(w)
    assert ok, why
    assert w.rows[0].tab_id == w.ctx.tab_id and w.pool.get_page(w.ctx.tab_id) is not None


def test_a_bridge_without_the_pool_hook_still_moves_the_worker(monkeypatch):
    """The three saves are best-effort: a bridge that lacks one never fails the move."""
    w = _world(monkeypatch)
    del w.bridge._emit_pool_status
    ok, why = _run(w)
    assert ok, why and w.rows[0].tab_id == w.ctx.tab_id and w.pool.get_page(w.ctx.tab_id) is not None


# ── the owner read has one home (audit #4 N1/N2) ────────────────────────────

def test_the_owner_probe_goes_through_the_shared_reader(monkeypatch):
    """The handover asks the one owner reader (`tab_owner.read_owner`), not its own probe."""
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True
    seen: list = []

    async def other_owner(client, tab_id=""):
        seen.append(client)
        return "somebody-else@example.com"
    monkeypatch.setattr(new_tab, "read_owner", other_owner, raising=False)
    ok, why = _run(w)
    assert seen, "the handover never called the shared owner reader"
    assert not ok and "wrong profile" in why and w.ctx.tab_id == "OLD"


@pytest.mark.parametrize("label", ["aka_1234", "  ", "not-an-email"])
def test_an_owner_label_that_is_not_an_email_never_rolls_back(monkeypatch, label):
    """A pool label that is no email at all is 'unknown', never a mismatch (normalize_owner)."""
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True
    w.pool.get_page("OLD").owner = label
    ok, why = _run(w)
    assert ok, why and w.browser.ctx_of(w.ctx.tab_id) == PROFILE_2


def test_a_label_that_is_the_email_in_another_case_still_matches(monkeypatch):
    """`Owner@Example.com` and the probe's lowercase email are the same account (normalize_owner)."""
    w = _world(monkeypatch, old_ctx=PROFILE_2)
    w.browser.refuse_ctx = True
    w.pool.get_page("OLD").owner = "ANTON@example.com"
    ok, why = _run(w)
    assert ok, why and w.browser.ctx_of(w.ctx.tab_id) == PROFILE_2


# ── N1: a Reparse queued during a handover must still run ────────────────────

def _now(_bridge, coro):
    """`schedule_coro` replacement that starts the coroutine in THIS loop, so the
    drain the production wiring installs is observable without a bg thread.
    """
    return asyncio.get_running_loop().create_task(coro)


def test_a_reparse_queued_during_a_handover_runs_when_the_handover_ends(monkeypatch):
    """I-68(a): `reconcile_once` QUEUES a manual pass that meets a running one and
    "runs it the moment that pass ends". The new-tab handover is the second holder
    of that flag and its release never looked at the queue — so a Reparse click
    during a handover was stranded until some unrelated later pass.

    The handover is paused at a known point (its new-chat readiness probe) so the
    click provably lands while the flag is held. Nothing triggers the drain: the
    handover ending must be enough.

    The drain is installed by the real `start_reconciler`, not by hand — branch A
    wired it with a call its own test did not reproduce, and the wiring it shipped
    crashed on this path (the report's §5). The loop task it also schedules is
    cancelled at once: the loop's own behaviour is pinned in
    `tests/test_live_reconcile.py` and `tests/test_reconcile_resilience.py`.
    """
    from app.services.live import reconcile
    ran = []
    reached = asyncio.Event()
    resume = asyncio.Event()

    async def counting_pass(p):
        p.deps.log("a real pass ran", "info")     # a real pass talks to its deps
        ran.append(p.source)
        return reconcile.Report()

    async def pause_at_the_proof(_reset_ctx):
        reached.set()
        await resume.wait()
        return True, "new chat ready"

    w = _world(monkeypatch)
    monkeypatch.setattr(reconcile, "_pass", counting_pass)
    monkeypatch.setattr(reconcile, "schedule_coro", _now)
    monkeypatch.setattr(new_tab, "wait_new_chat_ready", pause_at_the_proof)
    deps = SimpleNamespace(log=lambda m, l="info": w.logs.append((l, m)), stats=lambda: None)

    async def both():
        assert reconcile.start_reconciler(w.bridge, deps) is True
        w.bridge._url_reconciler.cancel()
        try:
            await w.bridge._url_reconciler
        except asyncio.CancelledError:
            pass
        task = asyncio.create_task(new_tab.handover(w.ctx, NEW_URL, timeout_sec=5))
        await reached.wait()                        # the handover now owns the flag
        report = await reconcile.reconcile_once(w.bridge, deps, "manual")
        assert ran == [], "nothing may run while the handover holds the flag"
        resume.set()
        ok, why = await task
        await asyncio.sleep(0.05)                   # the promise is "the moment", not "later"
        return report, ok, why

    report, ok, why = asyncio.run(both())
    assert ok, why
    assert report.error == "busy"                   # it could not run while held — correct
    assert ran == ["manual"], "the queued Reparse must run the moment the handover ends"
    assert w.bridge._reparse_queued is False
    assert w.bridge._auto_scan_running is False


def test_the_drain_runs_a_real_pass_not_a_placeholder(monkeypatch):
    """The drain `start_reconciler` installs must run a pass with the reconciler's
    own deps. Branch A wired `install_drain` with a lambda where a `LiveDeps` was
    expected (a module-level redefinition shadowed the import), so the drained
    pass died with AttributeError: 'function' object has no attribute 'log' on the
    background loop and the Reparse was lost (report §5).

    This goes through `pass_hold.release` — the call the handover's `finally`
    makes — so the wiring under test is the one production runs.
    """
    from app.services.live import pass_hold, reconcile
    ran = []

    async def counting_pass(p):
        p.deps.log("a real pass ran", "info")     # a real pass talks to its deps
        ran.append(p.source)
        return reconcile.Report()

    w = _world(monkeypatch)
    monkeypatch.setattr(reconcile, "_pass", counting_pass)
    monkeypatch.setattr(reconcile, "schedule_coro", _now)
    deps = SimpleNamespace(log=lambda m, l="info": w.logs.append((l, m)), stats=lambda: None)

    async def drained():
        assert reconcile.start_reconciler(w.bridge, deps) is True
        w.bridge._url_reconciler.cancel()
        try:
            await w.bridge._url_reconciler
        except asyncio.CancelledError:
            pass
        w.bridge._auto_scan_running = True      # a holder (the handover) owns the flag
        w.bridge._reparse_queued = True         # and a Reparse met it
        pass_hold.release(w.bridge)             # exactly what the handover's finally does
        await asyncio.sleep(0.05)

    asyncio.run(drained())
    assert ran == ["manual"], "the drained pass got the real deps and really ran"
    assert w.bridge._reparse_queued is False and w.bridge._auto_scan_running is False
