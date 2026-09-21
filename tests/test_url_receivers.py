"""S7: receiver flags — mark_receivers stamps (receiver, receiver_reason) on URL rows.

The ⊘ icon reads these flags; commit_urls + the reconciler refresh them.
Reasons: "" (receiving), "no tab assigned", "not running", "offline".
"""

import ast
from pathlib import Path

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.services.live import reconcile as rc
from app.services.live import url_policy as up
from app.ui.panels.url_queue import commit_urls
from app.ui.services import arena_serialize, undo_entries as entries
from tests.characterization.harness import build_bridge, build_stack
from tests.test_live_reconcile import fake_deps, tab


def _row(url="https://arena.ai/c/x", enabled=True, tab_id="t1"):
    return UrlRow.create(url, enabled=enabled, tab_id=tab_id)


def _pool(*tids, connected=True):
    pool = PagePool()
    for tid in tids:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://x/{tid}", title=f"T {tid}",
                               url="https://arena.ai/c/x", is_connected=connected))
    return pool


def test_mark_receivers_flags_all_four_states():
    rows = [
        _row(tab_id="t_ok"),
        _row(tab_id="t_off"),
        _row(tab_id="t_unchecked", enabled=False),
        _row(tab_id=""),
    ]
    pool = _pool("t_ok", "t_unchecked")  # connected; t_off absent from the pool
    changed = up.mark_receivers(rows, pool)
    assert [(r.receiver, r.receiver_reason) for r in rows] == [
        (True, ""),
        (False, "offline"),
        (False, "not running"),
        (False, "no tab assigned"),
    ]
    assert changed == 4  # every (flag, reason) tuple moved off the (False, "") default


def test_mark_receivers_returns_changed_count_and_is_idempotent():
    rows = [_row(tab_id="t1")]
    pool = _pool("t1")
    assert up.mark_receivers(rows, pool) == 1
    assert up.mark_receivers(rows, pool) == 0  # second pass: nothing changed
    rows[0].enabled = False
    assert up.mark_receivers(rows, pool) == 1  # (True, "") -> (False, "not running")
    rows[0].enabled = True
    assert up.mark_receivers(rows, pool, connected_ids=set()) == 1  # injected set wins
    assert (rows[0].receiver, rows[0].receiver_reason) == (False, "offline")
    assert up.mark_receivers(rows, pool, connected_ids=set()) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconcile_pass_refreshes_stale_flags_without_row_changes(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=0, tab_ids=["t1"], pool=PagePool())
    bridge = env.bridge
    bridge._page_pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/t1", title="T",
                                        url="https://arena.ai/chat0", is_connected=True))
    row = bridge.state.urls[0]
    row.receiver, row.receiver_reason = False, "offline"  # stale: the tab is up now
    d, rec = fake_deps(fetch_tabs=[tab("t1", url="https://arena.ai/chat0")])
    report = await rc.reconcile_once(bridge, d, "auto")
    assert (report.added, report.linked, report.removed) == (0, 0, 0)
    assert rec["commit"] == 1  # the flag flip alone commits (persist + emit)
    assert (row.receiver, row.receiver_reason) == (True, "")
    await rc.reconcile_once(bridge, d, "auto")
    assert rec["commit"] == 1  # idempotent: no second commit


def test_urls_to_js_emits_receiver_and_reason():
    d = {"urls": [
        {"id": "u1", "receiver": True, "receiver_reason": ""},
        {"id": "u2"},  # legacy dict: honest defaults
    ]}
    out = arena_serialize.urls_to_js(d)
    assert (out[0]["receiver"], out[0]["reason"]) == (True, "")
    assert (out[1]["receiver"], out[1]["reason"]) == (False, "")


def test_commit_urls_marks_before_save():
    from types import SimpleNamespace
    calls = []
    rows = [_row(tab_id="t1")]
    bridge = SimpleNamespace(state=SimpleNamespace(urls=rows), _page_pool=_pool("t1"),
                             _save_arena=lambda: calls.append("save"))
    commit_urls(bridge, undo=False)
    assert (rows[0].receiver, rows[0].receiver_reason) == (True, "")
    assert calls == ["save"]
    # missing pool: every row reads offline, nothing crashes
    rows2 = [_row(tab_id="t9")]
    bridge2 = SimpleNamespace(state=SimpleNamespace(urls=rows2), _page_pool=None,
                              _save_arena=lambda: None)
    commit_urls(bridge2, undo=False)
    assert (rows2[0].receiver, rows2[0].receiver_reason) == (False, "offline")


def test_undo_builders_restore_receiver_and_reason():
    snap = [{"id": "u1", "url": "https://a", "tab_id": "T1", "receiver": True, "reason": ""},
            {"id": "u2", "url": "https://b", "receiver": False, "reason": "offline"}]
    for build in (entries.url_rows_from_js, entries.arena_url_rows_from_js):
        rows = build(snap)
        assert [(r.receiver, r.receiver_reason) for r in rows] == [(True, ""), (False, "offline")]
    legacy = entries.url_rows_from_js([{"id": "u3", "url": "https://c"}])
    assert (legacy[0].receiver, legacy[0].receiver_reason) == (False, "")


def test_checkbox_flip_flows_through_commit():
    from types import SimpleNamespace
    rows = [_row(tab_id="t1")]
    bridge = SimpleNamespace(state=SimpleNamespace(urls=rows), _page_pool=_pool("t1"),
                             _save_arena=lambda: None)
    commit_urls(bridge, undo=False)
    assert rows[0].receiver is True
    rows[0].enabled = False  # the checkbox
    commit_urls(bridge, undo=False)
    assert (rows[0].receiver, rows[0].receiver_reason) == (False, "not running")
    rows[0].enabled = True
    commit_urls(bridge, undo=False)
    assert (rows[0].receiver, rows[0].receiver_reason) == (True, "")


def test_mark_receivers_source_lock():
    from tools.verify_quality import compute_cc_simple
    src = Path("app/services/live/url_policy.py").read_text()
    assert src.count("def mark_receivers(") == 1
    for token in ("enabled_tab_ids(", "pool._pages", "_connected_ids(", "_receiver_tuple("):
        assert token in src
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "mark_receivers")
    assert compute_cc_simple(node) <= 6  # the gate's own counter
