"""Tests for URL-row run gating in app/services/auto_connect.py.

Bug 2026-09-18: checked rows must gate which tabs run jobs. These helpers are
the rows -> tabs direction of the one-live-tab-<->-one-row invariant (I-33).
RULE 8: real UrlRow/PagePool/PageInfo, no Qt, no network.
"""

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.models import UrlRow
from app.services import auto_connect as ac

URL_A = "https://arena.ai/image/direct?model_a=max"
URL_B = "https://arena.ai/image/direct?model_b=max"


def row(url=URL_A, enabled=True, tab_id=""):
    return UrlRow.create(url, enabled=enabled, tab_id=tab_id)


def page(tab_id, url=URL_A, steady=True, connected=True, jobs=0):
    p = PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                 url=url, status=PageStatus.STEADY if steady else PageStatus.COOLDOWN,
                 is_connected=connected)
    p.jobs_completed = jobs
    return p


@pytest.mark.unit
def test_enabled_tab_ids_only_checked_linked_rows():
    urls = [row(tab_id="t1"), row(enabled=False, tab_id="t2"),
            row(tab_id=""), row(tab_id="t3")]
    assert ac.enabled_tab_ids(urls) == {"t1", "t3"}
    assert ac.enabled_tab_ids([]) == set()
    assert ac.enabled_tab_ids(None) == set()


@pytest.mark.unit
def test_row_for_tab_returns_owner_only():
    r1, r2 = row(tab_id="t1"), row(tab_id="t2")
    assert ac.row_for_tab([r1, r2], "t2") is r2
    assert ac.row_for_tab([r1, r2], "t9") is None
    assert ac.row_for_tab([], "t1") is None
    assert ac.row_for_tab([r1], "") is None


@pytest.mark.unit
def test_pick_url_for_tab_prefers_owner_over_first_enabled():
    first = row(url=URL_B, tab_id="t9")
    owner = row(tab_id="t1")
    picked = ac.pick_url_for_tab([first, owner], "t1")
    assert picked is owner  # owner beats earlier enabled row


@pytest.mark.unit
def test_pick_url_for_tab_falls_back_without_relinking():
    first = row(url=URL_B, tab_id="t9")
    picked = ac.pick_url_for_tab([first], "t1")
    assert picked is first  # record-only fallback…
    assert first.tab_id == "t9"  # …never re-binds to a foreign tab
    assert ac.pick_url_for_tab([], "t1") is None


@pytest.mark.unit
def test_pick_url_for_tab_skips_disabled_owner():
    disabled_owner = row(enabled=False, tab_id="t1")
    other = row(url=URL_B, tab_id="t2")
    assert ac.pick_url_for_tab([disabled_owner, other], "t1") is other


@pytest.mark.unit
def test_counts_in_counts_only_allowed_tabs():
    pool = PagePool()
    for tid in ("a", "b", "c"):
        pool.add_page(page(tid))
    pool.mark_busy("b", "job1")
    assert ac.counts_in(pool, {"a", "b"}) == (2, 1)
    assert ac.counts_in(pool, {"b"}) == (1, 0)
    assert ac.counts_in(pool, set()) == (0, 0)
    assert ac.counts_in(None, {"a"}) == (0, 0)


@pytest.mark.unit
def test_claim_unlinked_binds_exact_match_to_unowned_page():
    r = row(tab_id="")
    pages = [{"tab_id": "t1", "url": URL_A}, {"tab_id": "t2", "url": URL_B}]
    claimed = ac.claim_unlinked_from_pool([r], pages)
    assert claimed == 1 and r.tab_id == "t1"


@pytest.mark.unit
def test_claim_unlinked_never_steals_owned_page():
    owner = row(tab_id="t1")
    unlinked = row(tab_id="")  # same URL_A as owner's page
    pages = [{"tab_id": "t1", "url": URL_A}]
    assert ac.claim_unlinked_from_pool([owner, unlinked], pages) == 0
    assert unlinked.tab_id == ""


@pytest.mark.unit
def test_claim_unlinked_rejects_host_level_match():
    r = row(url="https://arena.ai/other/chat", tab_id="")
    pages = [{"tab_id": "t1", "url": URL_A}]
    assert ac.claim_unlinked_from_pool([r], pages) == 0
    assert r.tab_id == ""  # host match alone must never bind wrong chat tab


@pytest.mark.unit
def test_claim_unlinked_skips_disabled_and_garbage():
    disabled = row(tab_id="")
    disabled.enabled = False
    assert ac.claim_unlinked_from_pool([disabled], [{"tab_id": "t1", "url": URL_A}]) == 0
    assert ac.claim_unlinked_from_pool(None, None) == 0
    assert ac.claim_unlinked_from_pool([row(tab_id="")], [{}]) == 0


# ── Bridge module-level gating helpers (I-33 glue, headless-safe import) ──

import app.ui.panels._bridge_helpers as bridge_mod  # noqa: E402 (W1.6 move)


class _FakePool:
    def __init__(self, pages):
        self._snap = {"pages": pages}

    def status_snapshot(self):
        return self._snap


def _fake_bridge(urls, pages):
    from types import SimpleNamespace
    saved = []
    return SimpleNamespace(
        state=SimpleNamespace(urls=urls),
        _page_pool=_FakePool(pages),
        _save_arena=lambda: saved.append(1),
        _get_enabled_urls=lambda: [u for u in urls if u.enabled],
        _saved=saved,
    ), saved


@pytest.mark.unit
def test_urls_gate_error_codes():
    urls = [row(tab_id="")]
    br, _ = _fake_bridge(urls, [])
    assert bridge_mod._urls_gate_error(br, []) == "no enabled urls"
    assert bridge_mod._urls_gate_error(br, urls) == "no checked url linked to a tab"
    urls[0].tab_id = "t1"
    assert bridge_mod._urls_gate_error(br, urls) == ""


@pytest.mark.unit
def test_checked_tabs_ready_rescue_claims_and_persists():
    urls = [row(tab_id="")]
    br, saved = _fake_bridge(urls, [{"tab_id": "t1", "url": URL_A, "is_connected": True}])
    assert bridge_mod._checked_tabs_ready(br) == {"t1"}
    assert urls[0].tab_id == "t1" and saved  # claim persisted


@pytest.mark.unit
def test_dedupe_state_rows_repairs_and_counts():
    from app.core.models import UrlRow
    r1 = UrlRow.create(URL_A, tab_id="t1")
    r2 = UrlRow.create(URL_A, tab_id="t1")
    state_urls = [r1, r2]
    rows, removed = bridge_mod._dedupe_state_rows(state_urls)
    assert removed == 1 and len(rows) == 1 and state_urls == [r1]
    rows2, removed2 = bridge_mod._dedupe_state_rows(state_urls)
    assert removed2 == 0 and len(rows2) == 1  # idempotent


@pytest.mark.unit
def test_add_missing_rows_never_doubles_a_tab():
    from app.core.models import UrlRow
    urls = [UrlRow.create(URL_A, tab_id="t1")]
    added = bridge_mod._add_missing_rows(urls, [(URL_A, "t1"), (URL_A, "t2")])
    assert added == 1 and len(urls) == 2
    assert urls[1].tab_id == "t2" and urls[1].enabled is True
    assert bridge_mod._tab_already_owned(urls, "t1") is True
    assert bridge_mod._tab_already_owned(urls, "t9") is False
