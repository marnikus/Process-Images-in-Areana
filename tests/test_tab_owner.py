"""Owner probe at the seam: CDP reply → `page.owner` → the readable label.

`resolve_owners(pool)` runs the `account_email` probe (RULE 21 selectors) in
every pooled page that has a client, on the join and on every reconciler pass —
the same best-effort loop the worker badge uses. A failed or empty probe must
never clear a known email (the label may not regress to `aka_…`), and a dead
client must never raise into a join or a pass (RULE 15).
"""

import json

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.browser.site_adapter import get_selector
from app.core.tab_alias import AliasBook
from app.services.live import tab_owner as svc

pytestmark = pytest.mark.unit


class FakeClient:
    def __init__(self, reply="", fail=False):
        self.calls, self.reply, self.fail = [], reply, fail

    async def evaluate(self, js: str):
        if self.fail:
            raise RuntimeError("cdp down")
        self.calls.append(js)
        return self.reply


def pool_of(*tabs, clients=True, reply="", book=None):
    pool = PagePool(logger=lambda m, l="info": None, alias_book=book)
    for tid in tabs:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://x/{tid}", is_connected=True))
        if clients:
            pool.register_client(tid, FakeClient(reply=reply), object())
    return pool


@pytest.mark.asyncio
async def test_resolve_owners_labels_every_pooled_page():
    reply = json.dumps({"email": "marnikus@gmail.com", "via": "selector"})
    pool = pool_of("t1", "t2", reply=reply)
    assert await svc.resolve_owners(pool) == 2
    assert pool.get_page("t1").owner == "marnikus@gmail.com"
    assert pool.get_page("t1").alias == "marnikus@gmail.com_0001"
    labels = {p["tab_id"]: p["tab_label"] for p in pool.status_snapshot()["pages"]}
    assert labels == {"t1": "marnikus@gmail.com_0001", "t2": "marnikus@gmail.com_0002"}


@pytest.mark.asyncio
async def test_the_probe_payload_carries_the_site_adapter_selectors():
    pool = pool_of("t1", reply=json.dumps({"email": "a@b.co"}))
    await svc.resolve_owners(pool)
    sent = pool.get_clients("t1")[0].calls[0]
    for sel in get_selector("account_email").all_selectors():
        assert json.dumps(sel) in sent, sel


@pytest.mark.asyncio
async def test_an_empty_reply_never_clears_a_known_email():
    pool = pool_of("t1", reply="")
    pool.get_page("t1").owner = "marnikus@gmail.com"
    assert await svc.resolve_owners(pool) == 0
    assert pool.get_page("t1").owner == "marnikus@gmail.com"
    assert pool.get_page("t1").alias == "marnikus@gmail.com_0001"


@pytest.mark.asyncio
async def test_a_dead_client_is_skipped_without_raising():
    pool = pool_of("t1")
    pool.register_client("t1", FakeClient(fail=True), object())
    assert await svc.resolve_owners(pool) == 0
    assert pool.get_page("t1").owner == ""


@pytest.mark.asyncio
async def test_a_page_without_a_client_keeps_its_owner():
    pool = pool_of("t1", clients=False)
    pool.get_page("t1").owner = "kept@x.io"
    assert await svc.resolve_owners(pool) == 0
    assert pool.get_page("t1").owner == "kept@x.io"


@pytest.mark.asyncio
async def test_a_changed_account_updates_the_prefix_and_the_book():
    book = AliasBook({"t1": {"no": 7, "email": "old@x.io"}})
    pool = pool_of("t1", reply=json.dumps({"email": "new@x.io"}), book=book)
    assert await svc.resolve_owners(pool) == 1
    assert pool.get_page("t1").alias == "new@x.io_0007"
    assert book.owner_for("t1") == "new@x.io"
    assert book.no_for("t1") == 7


@pytest.mark.asyncio
async def test_an_unknown_pool_is_survivable():
    assert await svc.resolve_owners(None) == 0
