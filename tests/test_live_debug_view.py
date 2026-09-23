"""S9 · the Live Worker & Queue Debug payload — read-only, rides `progress_updated` (D-20 / D-22).

`debug_view.live_view(bridge)` extends S6's `cadence` with the queue head
(`queued`, `next_image` — the ONE eligibility rule, `core/run_scope`), the
receiver counts (S7's flag, never recomputed) and `run_state`. Workers ride the
existing `page_pool_updated` snapshot — nothing here reads the pool. No new
slot, no new signal.

RED at base: `AttributeError: module … has no attribute 'live_view'`.
"""

import copy
import json

import pytest

from app.core.models import UrlRow
from app.services.live import debug_view as dv, feed, url_policy
from app.ui.panels import layout_state
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit


def env_with(tmp_path, n_images=5, **kw):
    return build_bridge(tmp_path, build_stack(CORE_STACK), n_images=n_images, tab_ids=[], **kw)


def test_live_view_is_read_only(tmp_path, monkeypatch):
    env = env_with(tmp_path)
    before = copy.deepcopy(env.bridge.state)
    calls = []
    monkeypatch.setattr("app.browser.page_pool.PagePool.status_snapshot", lambda self: calls.append(1))
    out = dv.live_view(env.bridge)
    assert env.bridge.state == before
    assert calls == [] and isinstance(out, dict)


def test_next_queued_is_the_first_eligible_image_name(tmp_path):
    env = env_with(tmp_path)
    imgs = env.bridge.state.images
    imgs[0].status, imgs[1].status, imgs[2].status = "done", "processing", "failed"
    assert dv.next_queued(imgs) == imgs[2].filename  # failed is live-eligible (S4/S5), processing is not
    for img in imgs:
        img.status = "processing"
    assert dv.next_queued(imgs) == ""
    assert dv.next_queued([]) == ""


def test_queued_count_equals_the_eligibility_rule(tmp_path):
    env = env_with(tmp_path)
    imgs = env.bridge.state.images
    imgs[0].status, imgs[3].status = "done", "processing"
    view = dv.live_view(env.bridge)
    assert view["queued"] == len(feed.eligible_images(imgs)) == 3
    assert view["next_image"] == imgs[1].filename


def test_receiver_counts_match_the_flag(tmp_path, monkeypatch):
    rows = [UrlRow.create(f"https://arena.ai/{i}") for i in range(5)]
    for r in rows[:3]:
        r.receiver = True
    assert dv.receiver_counts(rows) == {"total": 5, "receivers": 3, "not_receivers": 2}
    assert dv.receiver_counts([]) == {"total": 0, "receivers": 0, "not_receivers": 0}
    env = env_with(tmp_path)
    env.bridge.state.urls = rows
    monkeypatch.setattr(url_policy, "mark_receivers", lambda *a, **k: pytest.fail("live_view must not recompute receivers"))
    assert dv.live_view(env.bridge)["receivers"] == {"total": 5, "receivers": 3, "not_receivers": 2}


def test_cadence_keys_are_present_and_typed(tmp_path):
    env = env_with(tmp_path)
    env.bridge._run_state = "live"
    view = dv.live_view(env.bridge)
    assert isinstance(view["url_interval_ms"], int) and isinstance(view["last_pass_at"], float)
    assert isinstance(view["passes"], int) and view["run_state"] == "live"
    assert dv.cadence(env.bridge).items() <= view.items()
    json.dumps(view)


def test_the_payload_rides_progress_updated(tmp_path):
    env = env_with(tmp_path)
    env.bridge._emit_arena_state()
    arena_keys = set(json.loads(env.recs["arena_state_updated"].calls[-1][0]))
    prog = json.loads(env.recs["progress_updated"].calls[-1][0])
    assert prog["live"]["queued"] == 5 and prog["live"]["next_image"] == env.bridge.state.images[0].filename
    assert prog["live"] == dv.live_view(env.bridge)
    assert "live" not in arena_keys and "workers" not in arena_keys  # arena_state_updated unchanged
    layout_state.emit_arena_state(env.bridge)
    assert set(json.loads(env.recs["arena_state_updated"].calls[-1][0])) == arena_keys


def test_no_captcha_wording_while_the_watcher_is_off(tmp_path):
    off = env_with(tmp_path)
    assert "captcha" not in json.dumps(dv.live_view(off.bridge)).lower()
    on = env_with(tmp_path / "on", watcher_on=True)
    on.bridge.config.set_state(watcher_captcha_timeout_sec=120)
    assert dv.live_view(on.bridge)["captcha_cap_sec"] == 120  # the cap the JS shows next to a waiting worker


def test_the_wait_reason_rides_the_live_view(tmp_path):
    """A-2: the supervisor's per-pass wait reason is published so the badge's sub-label can name it."""
    env = env_with(tmp_path)
    assert dv.live_view(env.bridge)["wait_reason"] == ""  # no loop yet → nothing to say
    env.bridge._live_reason = "all cooling"
    assert dv.live_view(env.bridge)["wait_reason"] == "all cooling"
    env.bridge._live_reason = None  # a pass is dispatching
    assert dv.live_view(env.bridge)["wait_reason"] == ""
