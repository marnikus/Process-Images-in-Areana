"""A Firefox that did not answer is not a Firefox with no tabs (round 11, D-4).

The owner: "fireFox is not detactable URL as Crome does. But also shoulbe be able detect URL
with pattern and add it to url list!".

Firefox's tabs do become URL rows — but only while its channel answers, and the reconciler
used to treat "the listing did not include it" as "its tabs are gone": misses advanced,
rows were removed after the threshold, the manual Reparse swept them away, and its pool
pages were marked stale. A Firefox waiting on its Allow dialog therefore looked *exactly*
like a browser with no tabs, and its rows and workers disappeared — which is what the
owner saw next to a working Chrome.

These tests run the real reconciler over a real (stub) Chrome and a real (stub) Firefox.
"""

import asyncio
import json

import pytest

from app.browser.page_pool import PagePool
from app.persistence.config_manager import ConfigManager
from app.services.live import reconcile as rc
from app.ui.panels import browser_tabs as bt
from app.ui.panels.page_pool import PagePoolMixin
from app.ui.panels.url_queue import UrlQueueMixin
from tests.fakes.rdp_stub_server import RdpStubServer
from tests.test_browser_endpoints import FakeChrome
from tests.test_panel_slots import make_host, make_state

pytestmark = pytest.mark.unit

BASE = 9310


@pytest.fixture
def firefox():
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def chrome():
    server = FakeChrome()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


@pytest.fixture(autouse=True)
def _clean_sessions():
    from app.browser.rdp import session as sess
    yield
    sess.close_all()


def _bridge(cfg, firefox, chrome, pattern="arena.ai"):
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="chrome",
                  url_pattern=pattern,
                  cdp_browsers={"chrome": {"enabled": True, "port": chrome.port},
                                "firefox": {"enabled": True, "port": firefox.port},
                                "edge": {"enabled": False}})
    pool = PagePool()
    pool._host, pool._port, pool._browser = "127.0.0.1", BASE, "chrome"
    host, logs = make_host([bt.BrowserTabsMixin, PagePoolMixin, UrlQueueMixin],
                           config=cfg, state=make_state(), _page_pool=pool)
    host._save_arena = lambda: None
    return host, logs


def _pass(host, source="auto"):
    """One reconcile pass on a private loop (the tests own the loop, not the panel)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(rc.reconcile_once(host, bt.live_deps(host), source))
    finally:
        loop.close()


def _rows(host):
    return {row.tab_id: row for row in host.state.urls if row.tab_id}


# ── D-5: detection parity with Chrome ────────────────────────────────────────

def test_a_pattern_matched_firefox_tab_becomes_a_url_row_like_a_chrome_tab(cfg, firefox, chrome):
    cfg.set_state(url_pattern="arena.ai")
    host, _logs = _bridge(cfg, firefox, chrome)
    _pass(host)
    rows = _rows(host)
    assert rows["ctx-3"].url == "https://arena.ai/c/1", "Firefox tabs are listing input too"
    assert rows["ctx-3"].browser == "firefox", "a row says which browser its tab belongs to"
    assert any(r.browser == "chrome" for r in host.state.urls), "and Chrome's keep theirs"


def test_the_pattern_decides_for_every_browser(cfg, firefox, chrome):
    host, _logs = _bridge(cfg, firefox, chrome, pattern="other.example")
    report = _pass(host)
    assert report.added == 0 and host.state.urls == []


def test_a_firefox_row_with_a_job_keeps_working_while_chrome_still_tracks(cfg, firefox, chrome):
    """Chrome's rows follow Chrome; Firefox's follow Firefox — one pass, two verdicts."""
    host, _logs = _bridge(cfg, firefox, chrome)
    _pass(host)
    chrome.tabs = chrome.tabs[:-1]         # a Chrome tab really did close (never mutate the fixture list)
    firefox.close()                        # Firefox is simply not answering any more
    for _ in range(3):
        _pass(host)
    rows = _rows(host)
    assert "ctx-3" in rows and "ctx-4" in rows, "an unanswered browser is a wait, not a removal"
    assert rows["ctx-3"].url == "https://arena.ai/c/1"


def test_a_waiting_allow_dialog_does_not_cost_the_firefox_rows(cfg, chrome):
    """The owner's case: Firefox is showing its dialog (bug 1) — and must not lose its URLs."""
    asking = RdpStubServer(prompt=True, prompt_wait=0.4)
    try:
        host, _logs = _bridge(cfg, asking, chrome)
        import app.browser.rdp.session as sess
        old_wait = sess.ALLOW_WAIT
        sess.ALLOW_WAIT = 0.2
        try:
            _pass(host)                     # parked: Firefox never gets to list its tabs
            _pass(host)
            _pass(host)
        finally:
            sess.ALLOW_WAIT = old_wait
        touched = (asking.connections, asking.prompts)
        assert asking.prompts <= 2, f"bounded, and never per pass: {touched}"
        assert (asking.connections, asking.prompts) == touched, \
            "the passes after the park must not dial (three passes ran above)"
        assert any(r.browser == "chrome" for r in host.state.urls), "Chrome was still listed"
        assert not [r for r in host.state.urls if r.browser == "firefox"], "nothing to show yet"
    finally:
        asking.close()


def test_the_reparse_is_what_clears_the_park_and_finds_the_urls(cfg, chrome):
    """The whole owner flow: dialog ignored → parked → user presses Reparse after Allow."""
    asking = RdpStubServer(prompt=True, prompt_wait=5.0)
    try:
        host, _logs = _bridge(cfg, asking, chrome)
        _pass(host)                       # automatic pass parks it: no Firefox rows yet
        assert not [r for r in host.state.urls if r.browser == "firefox"]
        asking.allow_pending()            # the user answers the dialog
        report = _pass(host, source="manual")   # the sweep rebuilds the list from open tabs
        firefox_rows = [r for r in host.state.urls if r.browser == "firefox"]
        assert len(firefox_rows) == 2 and report.added >= 2, host.state.urls
        assert {r.tab_id for r in firefox_rows} == {"ctx-3", "ctx-4"}
        assert asking.prompts >= 1
    finally:
        asking.close()


def test_the_reparse_after_the_user_allows_detects_the_firefox_urls(cfg, chrome):
    """Allow once, press Reparse: the Firefox URLs appear — the same way Chrome's do."""
    asking = RdpStubServer(prompt=True, prompt_wait=5.0)
    try:
        host, _logs = _bridge(cfg, asking, chrome)
        asking.allow_pending()              # the user answers the dialog
        report = _pass(host, source="manual")
        firefox_rows = [r for r in host.state.urls if r.browser == "firefox"]
        assert report.added >= 2 and len(firefox_rows) == 2, host.state.urls
        assert {r.tab_id for r in firefox_rows} == {"ctx-3", "ctx-4"}
        assert all(r.url.startswith("https://arena.ai/") for r in firefox_rows)
    finally:
        asking.close()


# ── D-4: no misses, no removal, no stale workers for an unanswered browser ───

def test_the_miss_counter_does_not_advance_for_a_browser_that_did_not_answer(cfg, firefox, chrome):
    host, _logs = _bridge(cfg, firefox, chrome)
    _pass(host)
    firefox.close()
    _pass(host)
    misses = host._reconcile_stats["misses"]
    assert all(count == 0 for count in misses.values()), misses


def test_its_pool_pages_are_not_marked_stale(cfg, firefox, chrome):
    host, _logs = _bridge(cfg, firefox, chrome)
    _pass(host)
    pool = host._page_pool
    assert pool.get_page("ctx-3") is not None, "Firefox tabs join the pool like any other"
    firefox.close()
    _pass(host)
    page = pool.get_page("ctx-3")
    assert page is not None and page.is_connected is True, \
        "a browser that said nothing has not told us this worker died"


def test_the_manual_reparse_keeps_the_rows_of_a_browser_that_did_not_answer(cfg, firefox, chrome):
    """Reparse rebuilds the list from open tabs — but only from the browsers that answered."""
    host, _logs = _bridge(cfg, firefox, chrome)
    _pass(host)
    firefox.close()
    _pass(host, source="manual")
    rows = _rows(host)
    assert set(rows) >= {"ctx-3", "ctx-4"}, host.state.urls


def test_the_pass_says_which_browser_did_not_answer_once_not_once_per_pass(cfg, firefox, chrome):
    host, logs = _bridge(cfg, firefox, chrome)
    _pass(host)
    firefox.close()
    _pass(host)
    _pass(host)
    named = [msg for lvl, msg in logs if lvl == "warn" and "firefox" in msg]
    assert len(named) == 1, f"one line per distinct reason, not one per pass: {named}"
    assert str(firefox.port) in named[0], "the line names the endpoint to look at"
