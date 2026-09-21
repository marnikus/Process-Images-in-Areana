"""The join path + the persisted numbers are one seam (D-5/D-6, integration).

`finish_pool_join` is the only place a tab becomes a pool row, so it owns three
things at once: read the account off the page (readable id), badge the tab with
that id, and leave the number on disk so the same tab keeps `_3045` tomorrow
(D0-2). All three must also hold when the probe is broken — a cosmetic read can
never break a join (RULE 15).

RED at `8db8ec6`: the join never probes, the badge prints the hex id and no
alias section is written.
"""

import json
from pathlib import Path

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.persistence.cooldown_store import load_aliases
from app.services.run_state import cooldowns_path
from app.ui.bridge_context import wire_page_pool
from app.ui.panels.page_pool import finish_pool_join
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.integration


class FakeClient:
    """CDP client double: a queue of `evaluate` replies, records every call."""

    def __init__(self, replies=(), fail=False):
        self.calls = []
        self.replies = list(replies)
        self.fail = fail

    async def evaluate(self, js: str):
        self.calls.append(js)
        if self.fail:
            raise RuntimeError("cdp down")
        return self.replies.pop(0) if self.replies else "ok"


def joined_bridge(tmp_path, replies=(), fail=False):
    """A real bridge + real pool + a join-shaped page and its client."""
    pool = PagePool(logger=lambda m, l="info": None)
    h = build_bridge(tmp_path, build_stack(CORE_STACK), pool=pool)
    client = FakeClient(replies, fail)
    info = PageInfo(tab_id="t1", ws_url="ws://x/t1", title="T", url="https://arena.ai/")
    return h.bridge, pool, client, info


@pytest.mark.asyncio
async def test_the_join_reads_the_account_and_persists_the_number(tmp_path):
    """One join: probe → `page.owner` → `{email}_{4}` badge → aliases on disk."""
    bridge, pool, client, info = joined_bridge(
        tmp_path, replies=[json.dumps({"email": "Marnikus@Gmail.com"})])
    await finish_pool_join(bridge, info, client, object())
    page = pool.get_page("t1")
    assert page.owner == "marnikus@gmail.com"
    assert page.alias == "marnikus@gmail.com_0001"
    assert "marnikus@gmail.com_0001" in client.calls[-1]   # the in-page badge
    assert client.calls[-1] != info.tab_id, "the hex id is no longer printed on the tab"
    saved = load_aliases(cooldowns_path(bridge))
    assert saved["t1"]["no"] == 1
    assert saved["t1"]["email"] == "marnikus@gmail.com"


@pytest.mark.asyncio
async def test_a_broken_probe_still_joins_with_the_aka_label(tmp_path):
    """D0-3: an unreadable account falls back to `aka_0001`, and nothing raises."""
    bridge, pool, client, info = joined_bridge(tmp_path, fail=True)
    await finish_pool_join(bridge, info, client, object())
    page = pool.get_page("t1")
    assert page.owner == ""
    assert page.alias == "aka_0001"
    assert "aka_0001" in client.calls[-1]
    assert load_aliases(cooldowns_path(bridge))["t1"]["no"] == 1


@pytest.mark.asyncio
async def test_the_join_does_not_lose_the_number_a_second_time(tmp_path):
    """A re-join of the same tab keeps `_0001` — the number is allocated once (D-5)."""
    bridge, pool, client, info = joined_bridge(tmp_path, replies=[json.dumps({"email": "m@gmail.com"})])
    await finish_pool_join(bridge, info, client, object())
    again = PageInfo(tab_id="t1", ws_url="ws://x/t1", title="T2", url="https://arena.ai/2")
    client2 = FakeClient([json.dumps({"email": "m@gmail.com"})])
    await finish_pool_join(bridge, again, client2, object())
    page = pool.get_page("t1")
    assert (page.alias_no, page.worker_no) == (1, 1)
    assert page.alias == "m@gmail.com_0001"


# ---- the other half of D0-2: a new session reads the numbers back ----------


def test_a_fresh_pool_reuses_the_saved_numbers(tmp_path):
    """`wire_page_pool` is the restart seam: it owns reading the alias section."""
    h = build_bridge(tmp_path, build_stack(CORE_STACK), pool=None)
    path = Path(cooldowns_path(h.bridge))
    path.write_text(json.dumps({"version": 1, "entries": {}, "stats": {},
                                "aliases": {"t1": {"no": 3045, "email": "m@gmail.com"}}}),
                    encoding="utf-8")
    pool = wire_page_pool(h.bridge)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/t1", is_connected=True,
                           status=PageStatus.STEADY))
    assert pool.get_page("t1").alias == "m@gmail.com_3045"
    pool.add_page(PageInfo(tab_id="t2", ws_url="ws://x/t2", is_connected=True))
    assert pool.get_page("t2").alias_no == 3046   # continues above the persisted maximum


def test_a_corrupt_store_never_blocks_the_pool(tmp_path):
    """Boundary: junk on disk → an empty book, a usable pool, no exception."""
    h = build_bridge(tmp_path, build_stack(CORE_STACK), pool=None)
    Path(cooldowns_path(h.bridge)).write_text("{not json", encoding="utf-8")
    pool = wire_page_pool(h.bridge)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/t1", is_connected=True))
    assert pool.get_page("t1").alias == "aka_0001"
