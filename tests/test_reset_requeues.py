"""Every reset re-queues (S4, D-16 / I-54) — on the real Bridge.

`reset_all` and `reset_image` return images to `pending` AND `selected=True`,
end in the one funnel (`feed.commit_queue`) — so the loop is woken, the count
is logged and the change is undoable — and `reset_image_state` has no
selection parameter any more, so `False` can never come back.
"""

import asyncio
import inspect
import json
import re

import pytest

from app.services.live import feed
from app.services.live.bus import live_bus
from app.ui.panels import run_control
from tests.characterization.harness import build_bridge, build_stack
from tests.characterization.test_batch_goldens import CORE_STACK

pytestmark = pytest.mark.unit


def settled_bridge(tmp_path, n=3):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=n)
    for i, im in enumerate(env.bridge.state.images):
        im.status = "completed" if i % 2 == 0 else "failed"
        im.selected = False
        im.error = "boom" if im.status == "failed" else None
        im.attempt_count = 2
        im.output_path = f"/out/{im.relative_path}"
    return env.bridge


def test_reset_all_requeues_every_image_selected(tmp_path):
    bridge = settled_bridge(tmp_path)
    assert json.loads(bridge.reset_all())["ok"] is True
    for im in bridge.state.images:
        assert (im.status, im.selected, im.error, im.attempt_count, im.output_path) == \
            ("pending", True, None, 0, None)
    assert feed.eligible_images(bridge.state.images) == bridge.state.images
    assert bridge.state.jobs == []


def test_reset_image_requeues_that_image_selected(tmp_path):
    bridge = settled_bridge(tmp_path)
    target, other = bridge.state.images[0], bridge.state.images[1]
    assert json.loads(bridge.reset_image(target.id))["ok"] is True
    assert (target.status, target.selected) == ("pending", True)
    assert (other.status, other.selected) == ("failed", False)   # untouched
    assert json.loads(bridge.reset_image("ghost"))["ok"] is False


async def test_reset_wakes_the_loop_and_logs_the_count(tmp_path):
    bridge = settled_bridge(tmp_path)
    logs = []
    bridge._log = lambda m, l="info": logs.append(m)
    bridge.reset_all()
    assert await live_bus(bridge).wait(0.05) == "reset_all"
    assert any(re.search(r"Reset all: 3 images re-queued", m) for m in logs), logs
    bridge.reset_image(bridge.state.images[0].id)
    assert await live_bus(bridge).wait(0.05) == "reset"


def test_reset_is_undoable(tmp_path):
    bridge = settled_bridge(tmp_path)
    bridge.bulk_select(False, "all")          # a history entry that remembers the settled queue
    before = [(im.status, im.selected) for im in bridge.state.images]
    bridge.reset_all()
    assert all(im.status == "pending" for im in bridge.state.images)
    bridge.undo()
    assert [(im.status, im.selected) for im in bridge.state.images] == before


def test_reset_image_state_has_no_selection_parameter():
    params = list(inspect.signature(run_control.reset_image_state).parameters)
    assert params == ["img"]
