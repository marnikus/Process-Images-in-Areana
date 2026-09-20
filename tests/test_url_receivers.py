"""UrlRow.receiver — one Python owner decides whether a row can take a job (S7, D-18/D-19, I-53).

`url_policy.mark_receivers` is the one writer (called by `commit_urls` and the
reconciler); `receiver_reason` names why a row is not a receiver
("unchecked" / "not linked" / "offline" / "busy"). The flag round-trips through
persistence, the JS serializer and both undo builders (RULE 13). Real PagePool,
real Bridge slots.
"""

import inspect
import json
from pathlib import Path

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.models import AppState, UrlRow
from app.core.persistence import load_state, save_state
from app.services import cooldown_service
from app.services.live import url_policy as up
from app.ui.services import arena_serialize, undo_entries
from tests.characterization.harness import build_bridge, build_stack
from tests.characterization.test_batch_goldens import CORE_STACK

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
REASONS = {"unchecked", "not linked", "offline", "busy"}


def page(tab_id, connected=True, image=None):
    info = PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=tab_id, url="https://arena.ai",
                    status=PageStatus.STEADY, is_connected=connected)
    info.current_image = image
    return info


def pool_with(*pages):
    pool = PagePool()
    for p in pages:
        pool.add_page(p)
    return pool


def rows():
    return [UrlRow.create("https://arena.ai/1", enabled=False, tab_id="t1"),   # unchecked
            UrlRow.create("https://arena.ai/2"),                               # not linked
            UrlRow.create("https://arena.ai/3", tab_id="t3"),                  # offline (not pooled)
            UrlRow.create("https://arena.ai/4", tab_id="t4"),                  # busy
            UrlRow.create("https://arena.ai/5", tab_id="t5")]                  # receiver


def test_unchecked_unlinked_offline_and_busy_rows_are_not_receivers():
    pool = pool_with(page("t1"), page("t4", image="a.png"), page("t5"), page("t6"))
    pool.get_page("t6").is_connected = False                       # add_page marks a page connected
    pooled = up.pooled_pages(pool)
    urls = rows() + [UrlRow.create("https://arena.ai/6", tab_id="t6")]
    changed = up.mark_receivers(urls, up.enabled_tab_ids(urls), pooled)
    assert changed == 6                                            # every row was decided once
    assert [(u.receiver, u.receiver_reason) for u in urls] == [
        (False, "unchecked"), (False, "not linked"), (False, "offline"), (False, "busy"),
        (True, ""), (False, "offline")]
    assert set(up.RECEIVER_REASONS) == REASONS


def test_a_checked_row_on_a_connected_pooled_tab_is_a_receiver():
    row = UrlRow.create("https://arena.ai/5", tab_id="t5")
    assert row.receiver is False                                   # an unmarked row never claims to receive
    pooled = up.pooled_pages(pool_with(page("t5")))
    assert up.receiver_reason(row, {"t5"}, pooled) == ""
    up.mark_receivers([row], {"t5"}, pooled)
    assert (row.receiver, row.receiver_reason) == (True, "")


def test_mark_receivers_reports_only_changes():
    urls = rows()
    pooled = up.pooled_pages(pool_with(page("t4", image="a.png"), page("t5")))
    assert up.mark_receivers(urls, up.enabled_tab_ids(urls), pooled) == 5
    assert up.mark_receivers(urls, up.enabled_tab_ids(urls), pooled) == 0
    urls[0].enabled = True                                         # the user checks the row
    assert up.mark_receivers(urls, up.enabled_tab_ids(urls), pooled) == 1
    assert urls[0].receiver_reason == "offline"                    # t1 is not pooled here


def test_the_flag_survives_serialization_and_persistence(tmp_path):
    state = AppState()
    state.urls = rows()
    up.mark_receivers(state.urls, up.enabled_tab_ids(state.urls), up.pooled_pages(pool_with(page("t5"))))
    js = arena_serialize.arena_to_js(state)["urls"]
    assert [(u["receiver"], u["receiver_reason"]) for u in js][:2] == [(False, "unchecked"), (False, "not linked")]
    assert js[4]["receiver"] is True
    save_state(state, tmp_path / "arena.json")
    back = load_state(tmp_path / "arena.json")
    assert [(u.receiver, u.receiver_reason) for u in back.urls] == [(u.receiver, u.receiver_reason) for u in state.urls]
    old = json.loads((tmp_path / "arena.json").read_text())        # an old file without the keys still loads
    for u in old["urls"]:
        u.pop("receiver"), u.pop("receiver_reason")
    (tmp_path / "old.json").write_text(json.dumps(old))
    assert load_state(tmp_path / "old.json").urls[0].receiver is False


def test_the_flag_survives_both_undo_builders():
    js = [{"id": "u1", "url": "https://arena.ai/1", "enabled": True, "status": "ready", "tab_id": "t1",
           "receiver": False, "receiver_reason": "busy"},
          {"id": "u2", "url": "https://arena.ai/2", "enabled": True, "status": "ready", "tab_id": "t2"}]
    for builder in (undo_entries.url_rows_from_js, undo_entries.arena_url_rows_from_js):
        a, b = builder(js)
        assert (a.receiver, a.receiver_reason) == (False, "busy")
        assert (b.receiver, b.receiver_reason) == (True, "")          # an old snapshot must not flash an icon


def test_commit_urls_recomputes_the_flag_through_the_real_slot(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), tab_ids=["t1"], pool=pool_with(page("t1")))
    bridge = env.bridge
    row = bridge.state.urls[0]
    bridge.toggle_url(row.id)                                      # checked → unchecked
    assert (row.receiver, row.receiver_reason) == (False, "unchecked")
    bridge.toggle_url(row.id)
    assert (row.receiver, row.receiver_reason) == (True, "")
    cooldown_service.set_tab_image(bridge._page_pool, "t1", "pic1.png")
    bridge.toggle_url(row.id)
    bridge.toggle_url(row.id)
    assert row.receiver_reason == "busy"
    js = json.loads(env.recs["arena_state_updated"].calls[-1][0])["urls"][0]
    assert (js["receiver"], js["receiver_reason"]) == (False, "busy")


def test_the_run_gate_is_not_reimplemented():
    src = (ROOT / "app/services/live/url_policy.py").read_text(encoding="utf-8")
    assert "enabled_tab_ids(" in src
    body = inspect.getsource(up.receiver_reason) + inspect.getsource(up.mark_receivers)
    assert "for u in" not in body and ".enabled and" not in body
    assert list(inspect.signature(up.mark_receivers).parameters) == ["rows", "allowed", "pooled"]


def test_the_receiver_field_is_appended_last():
    fields = [f.name for f in UrlRow.__dataclass_fields__.values()]
    assert fields[-2:] == ["receiver", "receiver_reason"]
    assert fields[:7] == ["id", "url", "enabled", "last_status", "last_checked", "error", "tab_id"]
