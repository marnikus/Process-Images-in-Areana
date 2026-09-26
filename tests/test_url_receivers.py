"""S7 · the receiver flag — one Python owner, the web UI only reflects it (D-18, I-53).

A row is a job receiver iff it is checked, linked, and its tab is pooled +
connected. `url_policy.mark_receivers` is the one writer (called by the
reconciler pass and by `commit_urls`), `receiver_reason` names why not
(`unchecked` / `not linked` / `offline` / `busy`), the flag lives on
`UrlRow.receiver` (persisted, serialized, undo-safe — RULE 13) and the run
gate is read from `auto_connect.enabled_tab_ids`, never re-implemented.

RED at base: `UrlRow` has no `receiver` field (`TypeError` / `AttributeError`).
"""

import json
import re
from pathlib import Path

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.core.persistence import load_state, save_state
from app.services.cooldown_service import set_tab_image
from app.services.live import url_policy as up
from app.ui.services import arena_serialize, undo_entries
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit
POLICY_SRC = Path(up.__file__).read_text(encoding="utf-8")

REASON_TEXT = {  # the exact tooltip wording — mirrored by tests/js/test_url_list_receiver_icon.mjs
    "unchecked": "Not used as job receiver — row unchecked",
    "not linked": "Not used as job receiver — no Chrome tab linked",
    "offline": "Not used as job receiver — tab not connected",
    "busy": "Not used as job receiver — tab busy with a job",
}


def pool_with(*tabs, connected=True):
    pool = PagePool(logger=lambda m, l="info": None)
    for tid in tabs:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://x/{tid}", title="T", url="https://arena.ai"))
        pool.get_page(tid).is_connected = connected  # `add_page` always connects; presence flips it later
    return pool


@pytest.mark.parametrize("reason, row, pool", [
    ("unchecked", UrlRow.create("https://arena.ai/c", enabled=False, tab_id="t1"), pool_with("t1")),
    ("not linked", UrlRow.create("https://arena.ai/c", enabled=True, tab_id=""), pool_with("t1")),
    ("offline", UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1"), pool_with("t1", connected=False)),
    ("offline", UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t9"), pool_with("t1")),  # not pooled at all
])
def test_unchecked_unlinked_and_offline_rows_are_not_receivers(reason, row, pool):
    assert row.receiver is False  # the default: an unmarked row never flashes as healthy
    assert up.mark_receivers([row], pool) == 0  # already False → no change reported
    assert row.receiver is False
    assert up.receiver_reason(row, pool) == reason
    assert up.receiver_title(row, pool) == REASON_TEXT[reason]


def test_a_checked_row_on_a_connected_pooled_tab_is_a_receiver():
    row = UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")
    pool = pool_with("t1")
    assert up.mark_receivers([row], pool) == 1
    assert row.receiver is True and up.receiver_reason(row, pool) == "" and up.receiver_title(row, pool) == ""


def test_a_tab_with_a_live_job_is_busy_not_a_receiver():
    row = UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")
    pool = pool_with("t1")
    set_tab_image(pool, "t1", "a.png")
    up.mark_receivers([row], pool)
    assert row.receiver is False and up.receiver_reason(row, pool) == "busy"


def test_mark_receivers_reports_only_changes():
    rows = [UrlRow.create("https://arena.ai/1", enabled=True, tab_id="t1"),
            UrlRow.create("https://arena.ai/2", enabled=True, tab_id="t2"),
            UrlRow.create("https://arena.ai/3", enabled=False, tab_id="t3")]
    pool = pool_with("t1", "t2", "t3")
    assert up.mark_receivers(rows, pool) == 2
    assert up.mark_receivers(rows, pool) == 0  # idempotent: no log / emit spam
    rows[0].enabled = False
    assert up.mark_receivers(rows, pool) == 1 and rows[0].receiver is False
    assert up.mark_receivers(rows, None) == 1  # no pool: the last receiver goes dark, once


def test_the_flag_survives_serialization():
    from app.core.models import AppState
    state = AppState()
    state.urls = [UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")]
    assert arena_serialize.arena_to_js(state)["urls"][0]["receiver"] is False
    state.urls[0].receiver = True
    assert arena_serialize.arena_to_js(state)["urls"][0]["receiver"] is True
    assert arena_serialize.urls_to_js({"urls": [{"id": "u", "url": "x"}]})[0]["receiver"] is False  # legacy dict: default


def test_the_flag_survives_persistence(tmp_path):
    from app.core.models import AppState
    state = AppState()
    state.urls = [UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")]
    state.urls[0].receiver = True
    save_state(state, tmp_path / "arena.json")
    assert load_state(tmp_path / "arena.json").urls[0].receiver is True
    legacy = json.loads((tmp_path / "arena.json").read_text(encoding="utf-8"))
    del legacy["urls"][0]["receiver"]
    (tmp_path / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert load_state(tmp_path / "legacy.json").urls[0].receiver is False  # an old file still loads


def test_both_undo_builders_keep_the_flag():
    js = [{"id": "u1", "url": "https://a", "tab_id": "T1", "receiver": True}, {"id": "u2", "url": "https://b"}]
    assert [r.receiver for r in undo_entries.url_rows_from_js(js)] == [True, False]
    assert [r.receiver for r in undo_entries.arena_url_rows_from_js(js)] == [True, False]


def test_the_flag_survives_undo_and_redo(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=["t1"])
    env.bridge._page_pool = pool_with("t1")
    row_id = env.bridge.state.urls[0].id
    env.bridge.toggle_url(row_id)  # checked → unchecked (commit #1; the tab also leaves the pool, D-4)
    env.bridge._page_pool.add_page(  # a re-checked row's tab rejoins via the reconciler's next pass
        PageInfo(tab_id="t1", ws_url="ws://x/t1", title="T", url="https://arena.ai/chat0"))
    env.bridge.toggle_url(row_id)  # back to checked (commit #2)
    assert env.bridge.state.urls[0].receiver is True
    env.bridge.undo()
    assert (env.bridge.state.urls[0].enabled, env.bridge.state.urls[0].receiver) == (False, False)
    env.bridge.redo()
    assert (env.bridge.state.urls[0].enabled, env.bridge.state.urls[0].receiver) == (True, True)


def test_commit_urls_recomputes_the_flag(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=["t1"])
    env.bridge._page_pool = pool_with("t1")
    row = env.bridge.state.urls[0]
    assert row.receiver is False  # nothing has committed yet
    env.bridge.toggle_url(row.id)
    assert row.enabled is False and row.receiver is False
    assert env.bridge._page_pool.get_page("t1") is None  # the checkbox is the pool gate (D-4)
    env.bridge._page_pool.add_page(  # the reconciler re-joins a checked row's tab on its next pass
        PageInfo(tab_id="t1", ws_url="ws://x/t1", title="T", url="https://arena.ai/chat0"))
    env.bridge.toggle_url(row.id)
    assert row.enabled is True and row.receiver is True  # the icon follows the checkbox instantly
    pushed = json.loads(env.recs["arena_state_updated"].calls[-1][0])["urls"][0]
    assert pushed["receiver"] is True


@pytest.mark.asyncio
async def test_the_reconciler_marks_receivers_after_presence(tmp_path):
    from types import SimpleNamespace
    from app.services.live import reconcile as rc
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=["t1"])
    env.bridge._page_pool = pool_with("t1")
    tabs = [SimpleNamespace(id="t1", title="T", url="https://arena.ai/chat0", ws_url="ws://x/t1", type="page")]

    async def fetch():
        return tabs

    async def join(ws):
        pass
    deps = rc.LiveDeps(fetch_tabs=fetch, join_tab=join, commit=env.bridge._save_arena, log=env.bridge._log)
    await rc.reconcile_once(env.bridge, deps, "auto")
    assert env.bridge.state.urls[0].receiver is True
    assert json.loads(env.recs["arena_state_updated"].calls[-1][0])["urls"][0]["receiver"] is True
    tabs.clear()  # Chrome closed the tab → presence flags it → the row stops being a receiver
    await rc.reconcile_once(env.bridge, deps, "auto")
    assert env.bridge.state.urls[0].receiver is False


def test_the_run_gate_is_not_reimplemented():
    """One owner (RULE 10): the policy reads `enabled_tab_ids`; it never filters `.enabled` rows itself."""
    assert "enabled_tab_ids(" in POLICY_SRC
    assert not re.search(r"for \w+ in .*:\s*\n\s*if .*\.enabled\b", POLICY_SRC)
    assert UrlRow.__dataclass_fields__["receiver"].default is False
    # appended last (RULE 13): positional constructors survive; I-64's `typed` came after it
    assert list(UrlRow.__dataclass_fields__)[-2:] == ["receiver", "typed"]
