"""live.debug_view.live_view — the queue/cadence half of the Live Worker & Queue Debug window (S9, D-22).

Read-only, rides the existing `progress_updated.live` payload (no slot, no
signal): queued count = S4's one eligibility rule, the first queued image's
name, receiver counts from S7's flag (never recomputed), the run/wait state
and S6's cadence. The workers half rides `page_pool_updated` unchanged.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from app.core.models import UrlRow
from app.services.live import debug_view, feed, supervisor, url_policy
from app.ui.panels import layout_state
from tests.characterization.harness import build_bridge, build_stack, make_images
from tests.characterization.test_batch_goldens import CORE_STACK

pytestmark = pytest.mark.unit


def img(name, status="pending", selected=True):
    return SimpleNamespace(relative_path=f"dir/{name}", status=status, selected=selected)


def test_live_view_is_read_only(tmp_path, monkeypatch):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=2)
    from app.browser.page_pool import PagePool
    pool = PagePool()
    env.bridge._page_pool = pool
    calls = []
    monkeypatch.setattr(pool, "status_snapshot", lambda: calls.append(1) or {"pages": []})
    before = copy.deepcopy(env.bridge.state.to_dict())
    view = debug_view.live_view(env.bridge)
    assert env.bridge.state.to_dict() == before
    assert calls == []                                          # the workers half is the pool's own signal
    assert view["queued"] == 2 and view["next_image"] == "pic1.png"


def test_next_queued_is_the_first_eligible_image_name():
    images = [img("a.png", "completed"), img("b.png", "processing"), img("c.png", "pending", selected=False),
              img("d.png", "failed"), img("e.png", "pending"), img("f.png", "selected")]
    assert debug_view.next_queued(images) == "e.png"
    assert debug_view.next_queued([]) == ""
    assert debug_view.next_queued([img("x.png", "processing")]) == ""


def test_queued_count_equals_the_eligibility_rule(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=4)
    env.bridge.state.images[0].status = "completed"
    env.bridge.state.images[1].selected = False
    view = debug_view.live_view(env.bridge)
    assert view["queued"] == len(feed.eligible_images(env.bridge.state.images)) == 2
    assert view["next_image"] == "pic3.png"


def test_receiver_counts_match_the_flag(monkeypatch):
    rows = [UrlRow.create(f"https://arena.ai/{i}") for i in range(5)]
    for r in rows[:3]:
        r.receiver = True
    rows[3].receiver_reason, rows[4].receiver_reason = "offline", "busy"
    spy = []
    monkeypatch.setattr(url_policy, "mark_receivers", lambda *a, **k: spy.append(a))
    assert debug_view.receiver_counts(rows) == {"total": 5, "receivers": 3, "not_receivers": 2,
                                                "reasons": {"offline": 1, "busy": 1}}
    assert spy == []                                            # S7 owns the flag; this only counts


def test_cadence_keys_are_present_and_typed(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK))
    view = debug_view.live_view(env.bridge)
    assert isinstance(view["url_interval_ms"], int) and isinstance(view["last_pass_at"], float)
    assert isinstance(view["run_state"], str) and view["run_state"] == "idle"
    assert view["wait_reason"] == "" and isinstance(view["passes"], int)
    json.dumps(view)                                            # JSON-serializable, always
    supervisor.live_state(env.bridge).reason = "no_tab"
    assert debug_view.live_view(env.bridge)["wait_reason"] == "no_tab"


def test_the_payload_rides_progress_updated_and_arena_state_is_unchanged(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    layout_state.emit_arena_state(env.bridge)
    prog = json.loads(env.recs["progress_updated"].calls[-1][0])
    assert prog["live"]["queued"] == 1 and prog["live"]["next_image"] == "pic1.png"
    assert prog["live"]["receivers"]["total"] == 1
    arena = json.loads(env.recs["arena_state_updated"].calls[-1][0])
    assert "live" not in arena                                  # the JS arena contract stays put


def test_no_captcha_wording_while_the_watcher_is_off(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)   # DEFAULT_SESSION: watcher OFF
    text = json.dumps(debug_view.live_view(env.bridge)).lower()
    assert "captcha" not in text
