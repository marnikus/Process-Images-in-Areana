"""Firefox account name & visual tab ID — integration tests (2026-09-25).

Covers the requirement's acceptance criteria: URL List / Page Pool share the
same verified display name, overlay ``N# account`` matches visual number,
no duplicate overlays, fallback chain without worker loss, reconnect and stale
handling, and Chrome unchanged.

Uses real pool + alias book, fake evaluate callables for the probe (macro
integration), and the worker_badge JS builders directly (RULE 8: real DOM
payloads are inspected, CDP is faked).
"""

import asyncio
import json

import pytest

from app.browser.page_pool import PagePool, tab_label_of
from app.browser.page_status import PageInfo, PageStatus
from app.browser.uivision import pool_tabs as pt
from app.browser.worker_badge import (
    FIREFOX_ATTR,
    FirefoxBadgeSpec,
    build_firefox_badge_js,
    build_firefox_badge_clear_js,
    build_worker_badge_js,
    WorkerBadgeSpec,
)
from app.browser.uivision.firefox_helpers import (
    build_firefox_account_probe_js,
    interpret_firefox_account,
)
from app.browser.site_adapter import get_selector
from app.core.tab_alias import AliasBook
from app.services.live.firefox_badges import assert_firefox_badges
from app.services.live.firefox_owner import resolve_firefox_owners

pytestmark = pytest.mark.unit


class FakeFirefoxClient:
    def __init__(self, replies):
        self.calls = []
        self.replies = list(replies)

    async def evaluate(self, js: str):
        self.calls.append(js)
        if not self.replies:
            return json.dumps({"email": "", "via": "scan"})
        return self.replies.pop(0)


def firefox_page(pool, tab_id, profile, owner=""):
    page = pt.FirefoxPageInfo(tab_id=tab_id, profile=profile, profile_dir=f"/tmp/{profile}", owner=owner, is_connected=True)
    pool.add_page(page)
    return pool.get_page(tab_id)


# 1. Before account detected use profile name, never aka
def test_firefox_uses_profile_as_temp_name_before_probe():
    pool = PagePool(logger=lambda m, l="info": None)
    page = firefox_page(pool, "Profile1_tab1", "Profile1", owner="")
    assert tab_label_of(pool, "Profile1_tab1") == "Profile1"
    snap = pool.status_snapshot()
    assert snap["pages"][0]["tab_label"] == "Profile1"
    assert snap["pages"][0]["tab_label"] != "aka_0001"
    assert page.label == "Profile1"


# 2. Success: detected account replaces profile in both URL List and Page Pool
@pytest.mark.asyncio
async def test_success_detection_updates_both_views_and_overlay():
    pool = PagePool(logger=lambda m, l="info": None)
    page = firefox_page(pool, "Profile1_tab1", "Profile1")
    assert pool.status_snapshot()["pages"][0]["tab_label"] == "Profile1"

    async def evaluate(tab_id, js):
        return json.dumps({"email": "mailreceiverpro@gmail.com", "via": "selector"})

    await resolve_firefox_owners(pool, evaluate=evaluate)
    assert tab_label_of(pool, "Profile1_tab1") == "mailreceiverpro@gmail.com"
    assert pool.status_snapshot()["pages"][0]["tab_label"] == "mailreceiverpro@gmail.com"

    # overlay N# account matches visual number
    spec = FirefoxBadgeSpec(worker_no=page.worker_no, account=tab_label_of(pool, "Profile1_tab1"))
    js = build_firefox_badge_js(spec)
    assert f"{page.worker_no}# mailreceiverpro@gmail.com" in js
    assert FIREFOX_ATTR in js
    assert "position:fixed" in js and "left:50%" in js and "pointer-events:none" in js


# 3. Delayed load: first probe empty, retry finds email (bounded delay)
@pytest.mark.asyncio
async def test_delayed_load_retry_eventually_succeeds():
    pool = PagePool(logger=lambda m, l="info": None)
    page = firefox_page(pool, "Profile1_tab1", "Profile1")
    # make title look loading to trigger retry heuristic
    page.title = "Loading..."
    calls = []

    async def evaluate(tab_id, js):
        calls.append(1)
        if len(calls) == 1:
            return json.dumps({"email": "", "via": "scan"})
        return json.dumps({"email": "delayed@mail.com", "via": "selector"})

    await resolve_firefox_owners(pool, evaluate=evaluate)
    assert tab_label_of(pool, "Profile1_tab1") == "delayed@mail.com"
    assert len(calls) == 2  # retried once


# 4. Missing element: probe never finds email → fallback to profile, worker not lost
@pytest.mark.asyncio
async def test_missing_element_uses_profile_fallback_without_losing_worker():
    pool = PagePool(logger=lambda m, l="info": None)
    page = firefox_page(pool, "Profile1_tab1", "Profile1")
    worker_before = page.worker_no

    async def evaluate(tab_id, js):
        return json.dumps({"email": "", "via": "scan"})

    class Bridge:
        def __init__(self):
            self.logs = []

        def _log(self, msg, level="info"):
            self.logs.append((level, msg))

    bridge = Bridge()
    await resolve_firefox_owners(pool, bridge=bridge, evaluate=evaluate)
    assert pool.get_page("Profile1_tab1") is not None
    assert pool.get_page("Profile1_tab1").worker_no == worker_before
    assert tab_label_of(pool, "Profile1_tab1") == "Profile1"
    # warning includes worker id, profile, stage, safe reason, no HTML
    assert any("profile Profile1" in msg and "stage initial_scan" in msg for _, msg in bridge.logs)
    assert all("<div" not in msg for _, msg in bridge.logs)


# 5. Duplicate account names across profiles remain separate workers
def test_duplicate_account_names_remain_separate_workers():
    pool = PagePool(logger=lambda m, l="info": None)
    p1 = firefox_page(pool, "ProfA_tab1", "ProfA", owner="same@mail.com")
    p2 = firefox_page(pool, "ProfB_tab1", "ProfB", owner="same@mail.com")
    assert p1.tab_id != p2.tab_id
    assert p1.worker_no != p2.worker_no
    snap = pool.status_snapshot()
    labels = {p["tab_id"]: p["tab_label"] for p in snap["pages"]}
    assert labels["ProfA_tab1"] == labels["ProfB_tab1"] == "same@mail.com"
    # overlays have distinct numbers but same account
    js1 = build_firefox_badge_js(FirefoxBadgeSpec(worker_no=p1.worker_no, account="same@mail.com"))
    js2 = build_firefox_badge_js(FirefoxBadgeSpec(worker_no=p2.worker_no, account="same@mail.com"))
    assert f"{p1.worker_no}# same@mail.com" in js1
    assert f"{p2.worker_no}# same@mail.com" in js2
    assert p1.worker_no != p2.worker_no


# 6. Reconnect keeps worker number via revive, account change updates label
def test_reconnect_and_account_change_update_label():
    pool = PagePool(logger=lambda m, l="info": None)
    page = firefox_page(pool, "Profile1_tab1", "Profile1", owner="old@mail.com")
    worker_before = page.worker_no
    page.title = "Old Title"
    # simulate disconnect (presence sync)
    page.is_connected = False
    # reconnect with same tab_id but new title (session store has no owner)
    recon = pt.FirefoxPageInfo(tab_id="Profile1_tab1", profile="Profile1", profile_dir="/tmp/Profile1", is_connected=True, title="New Title")
    pool.add_page(recon)
    after = pool.get_page("Profile1_tab1")
    assert after.worker_no == worker_before
    assert after.title == "New Title"
    # owner still old until probe re-reads — probe would update to new account
    assert tab_label_of(pool, "Profile1_tab1") == "old@mail.com"
    # simulate probe finding new account after navigation
    after.owner = "new@mail.com"
    assert tab_label_of(pool, "Profile1_tab1") == "new@mail.com"


# 7. Stale overlay replacement: second badge removes first, never duplicates
def test_firefox_overlay_is_idempotent_and_replaces_stale():
    spec1 = FirefoxBadgeSpec(worker_no=2, account="mailreceiverpro@gmail.com")
    js1 = build_firefox_badge_js(spec1)
    assert js1.count(f"[{FIREFOX_ATTR}]") >= 1
    assert ".remove()" in js1
    assert "2# mailreceiverpro@gmail.com" in js1
    spec2 = FirefoxBadgeSpec(worker_no=2, account="other@mail.com")
    js2 = build_firefox_badge_js(spec2)
    assert "2# other@mail.com" in js2
    # clear removes only firefox overlay
    clear_js = build_firefox_badge_clear_js()
    assert FIREFOX_ATTR in clear_js and ".remove()" in clear_js
    assert "data-arena-worker" not in clear_js


# 8. Firefox display cache: last-known via AliasBook survives empty probe
@pytest.mark.asyncio
async def test_last_known_account_is_fallback_before_profile():
    book = AliasBook({"Profile1_tab1": {"no": 5, "email": "lastknown@mail.com", "seen": 1.0}})
    pool = PagePool(alias_book=book, logger=lambda m, l="info": None)
    page = firefox_page(pool, "Profile1_tab1", "Profile1", owner="")
    # after add, owner seeded from book
    assert tab_label_of(pool, "Profile1_tab1") == "lastknown@mail.com"
    # empty probe should keep lastknown, not downgrade to profile
    async def evaluate(tab_id, js):
        return json.dumps({"email": "", "via": "scan"})

    await resolve_firefox_owners(pool, evaluate=evaluate)
    assert tab_label_of(pool, "Profile1_tab1") == "lastknown@mail.com"


# 9. Site adapter selector covers evidence div
def test_site_adapter_includes_firefox_evidence_selector():
    sel = get_selector("account_email")
    all_sels = sel.all_selectors()
    assert any("font-heading" in s and "truncate" in s for s in all_sels)
    # evidence leaf uses min-w-0 and truncate
    assert any("min-w-0" in s for s in all_sels) or any("font-heading" in s for s in all_sels)
    # probe JS contains those selectors
    js = build_firefox_account_probe_js()
    for s in all_sels:
        assert json.dumps(s) in js


# 10. Probe interpret never exposes HTML
def test_interpret_never_exposes_html():
    raw = json.dumps({"email": "mailreceiverpro@gmail.com", "via": "selector", "candidates": ["mailreceiverpro@gmail.com"]})
    out = interpret_firefox_account(raw)
    assert out["email"] == "mailreceiverpro@gmail.com"
    assert interpret_firefox_account("")["email"] == ""
    assert interpret_firefox_account("not json <div>xxx</div>")["email"] == ""
    assert interpret_firefox_account(None)["email"] == ""


# 11. Chrome unchanged: still uses aka fallback
def test_chrome_still_uses_aka_fallback():
    pool = PagePool(logger=lambda m, l="info": None)
    info = PageInfo(tab_id="chrome1", browser="chrome", is_connected=True)
    pool.add_page(info)
    assert tab_label_of(pool, "chrome1") == "aka_0001"
    assert pool.status_snapshot()["pages"][0]["tab_label"] == "aka_0001"
    pool.get_page("chrome1").owner = "marnikus@gmail.com"
    assert tab_label_of(pool, "chrome1") == "marnikus@gmail.com_0001"
    js = build_worker_badge_js(WorkerBadgeSpec(worker_no=1, tab_id="chrome1", label="marnikus@gmail.com_0001"))
    assert "#1" in js and "marnikus@gmail.com_0001" in js


# 12. Visual number matches worker_no for Firefox overlay
@pytest.mark.asyncio
async def test_firefox_overlay_number_matches_worker_no():
    pool = PagePool(logger=lambda m, l="info": None)
    p1 = firefox_page(pool, "Profile1_tab1", "Profile1")
    p2 = firefox_page(pool, "Profile1_tab2", "Profile1")
    # use evaluate that returns distinct emails
    async def evaluate(tab_id, js):
        return json.dumps({"email": f"{tab_id}@mail.com", "via": "selector"})

    await resolve_firefox_owners(pool, evaluate=evaluate)
    for pid in ["Profile1_tab1", "Profile1_tab2"]:
        page = pool.get_page(pid)
        label = tab_label_of(pool, pid)
        js = build_firefox_badge_js(FirefoxBadgeSpec(worker_no=page.worker_no, account=label))
        assert f"{page.worker_no}# {label}" in js


# 13. Badge service updates when account changes
@pytest.mark.asyncio
async def test_badge_updates_when_account_changes():
    pool = PagePool(logger=lambda m, l="info": None)
    page = firefox_page(pool, "Profile1_tab1", "Profile1", owner="old@mail.com")
    client = FakeFirefoxClient([
        json.dumps({"email": "new@mail.com", "via": "selector"}),
        "ok",
    ])
    # register fake client for pool so badge can be drawn via client path
    pool.register_client("Profile1_tab1", client, object())
    # first badge with old account
    await assert_firefox_badges(pool)
    assert any("old@mail.com" in c for c in client.calls)
    client.calls.clear()
    # now owner probe changes account
    async def evaluate(tab_id, js):
        return json.dumps({"email": "new@mail.com", "via": "selector"})
    await resolve_firefox_owners(pool, evaluate=evaluate)
    await assert_firefox_badges(pool)
    assert any("new@mail.com" in c for c in client.calls)
