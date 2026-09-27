"""Unit contracts of the I-68 helpers (held listing, Reparse queue, sweep keeps)."""

from types import SimpleNamespace

import pytest

from app.browser.uivision.pool_tabs import is_firefox_tab_id, tab_id_for
from app.core.models import UrlRow
from app.services.live import reconcile as rc
from app.services.live import reconcile_rows as rr
from app.services.live.listing import Listing, held_keys
from app.ui.panels import browser_tabs

pytestmark = pytest.mark.unit


def test_listing_is_the_answered_list_plus_held_keys():
    listing = Listing(["a", "b"], held=["c1", "", "c2"])
    assert list(listing) == ["a", "b"] and listing.held == {"c1", "c2"}
    assert held_keys(listing) == {"c1", "c2"}
    assert held_keys(["a"]) == frozenset() and held_keys(None) == frozenset()


def test_is_firefox_tab_id_matches_only_the_built_shape():
    assert is_firefox_tab_id(tab_id_for("C:/p/9THrgpBc.Profile1", 2))
    for other in ("A1B2C3D4E5F60718293A4B5C6D7E8F90", "ws://h/devtools/page/X", "_tab1", "", None):
        assert not is_firefox_tab_id(other)


def test_scan_reason_prefers_the_failure_then_the_missing_notes():
    assert browser_tabs._scan_reason(SimpleNamespace()) == ""
    assert browser_tabs._scan_reason(SimpleNamespace(_scan_failed="boom", _scan_missing={"c": "x"})) == "boom"
    assert browser_tabs._scan_reason(SimpleNamespace(_scan_failed="", _scan_missing={"c": "refused"})) == "refused"


def _bridge(urls=(), pooled=()):
    pool = SimpleNamespace(_pages={k: object() for k in pooled})
    return SimpleNamespace(state=SimpleNamespace(urls=list(urls)), _page_pool=pool)


def test_chrome_keys_are_rows_and_pool_minus_firefox_ids():
    ff = tab_id_for("x/9THrgpBc.Profile1", 1)
    rows = [UrlRow.create("https://a/1", tab_id="c1"), UrlRow.create("https://a/2", tab_id=ff),
            UrlRow.create("https://a/3")]
    assert browser_tabs._chrome_keys(_bridge(rows, pooled=["c2", ff])) == {"c1", "c2"}


def test_firefox_only_holds_chrome_or_waits(monkeypatch):
    monkeypatch.setattr(browser_tabs, "_firefox_rows", lambda b: ["ff-tab"])
    listing = browser_tabs._firefox_only(_bridge([UrlRow.create("https://a", tab_id="c1")]), "refused")
    assert list(listing) == ["ff-tab"] and listing.held == {"c1"}
    monkeypatch.setattr(browser_tabs, "_firefox_rows", lambda b: [])
    with pytest.raises(rc.ScanUnavailable, match="refused"):
        browser_tabs._firefox_only(_bridge(), "refused")


def test_queue_if_manual_logs_once_and_ignores_auto():
    lines, bridge = [], SimpleNamespace()
    deps = SimpleNamespace(log=lambda m, level="info": lines.append(m))
    rc._queue_if_manual(bridge, deps, "auto")
    assert not getattr(bridge, "_reparse_queued", False)
    rc._queue_if_manual(bridge, deps, "manual")
    rc._queue_if_manual(bridge, deps, "manual")
    assert bridge._reparse_queued is True and len(lines) == 1


def test_sweep_keeps_busy_only_in_a_live_run_and_always_held():
    spec = SimpleNamespace(busy_tabs={"t1"})
    idle = SimpleNamespace(bridge=SimpleNamespace(_run_state="idle"), tabs=Listing([], held=["c9"]))
    assert rr._sweep_keeps(idle, spec) == (set(), {"c9"})
    live = SimpleNamespace(bridge=SimpleNamespace(_run_state="paused"), tabs=[])
    assert rr._sweep_keeps(live, spec) == ({"t1"}, frozenset())


def test_kept_note_names_each_reason():
    assert rr._kept_note(0, 0) == ""
    assert rr._kept_note(1, 0) == " (kept: 1 job running)"
    assert rr._kept_note(2, 3) == " (kept: 2 job running, 3 browser not answering)"
