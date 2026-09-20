"""S4: both resets return images to pending AND selected (D-6R, real Bridge)."""

import inspect
import json
import re

import pytest

from app.services.live.bus import live_bus
from app.services.live.feed import eligible_images
from app.ui.panels.queue_scan import push_queue_undo
from app.ui.panels.run_control import reset_image_state
from tests.characterization.harness import build_bridge, build_stack


def _after_a_run(bridge):
    """completed/failed leftovers with errors, attempts and stale assignments."""
    for i, img in enumerate(bridge.state.images):
        img.status = "completed" if i % 2 == 0 else "failed"
        img.error = "boom"
        img.attempt_count = 2
        img.selected = False
        img.assigned_url_id = "url_gone"
        img.output_path = "/tmp/old.png"


@pytest.mark.unit
def test_reset_all_requeues_every_image_selected(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=3)
    bridge = env.bridge
    _after_a_run(bridge)
    assert json.loads(bridge.reset_all()) == {"ok": True}
    for img in bridge.state.images:
        assert img.status == "pending"
        assert img.selected is True
        assert img.error is None
        assert img.attempt_count == 0
        assert img.assigned_url_id is None
        assert img.output_path is None
    assert eligible_images(bridge.state.images) == bridge.state.images


@pytest.mark.unit
def test_reset_image_requeues_that_image_selected(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=2)
    bridge = env.bridge
    _after_a_run(bridge)
    target = bridge.state.images[0]
    assert json.loads(bridge.reset_image(target.id)) == {"ok": True}
    assert (target.status, target.selected, target.error, target.attempt_count) == ("pending", True, None, 0)
    other = bridge.state.images[1]
    assert (other.status, other.selected) == ("failed", False)  # untouched
    assert json.loads(bridge.reset_image("ghost")) == {"ok": False, "error": "not found"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_wakes_the_loop_and_logs_the_count(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=3)
    bridge = env.bridge
    _after_a_run(bridge)
    bridge.reset_all()
    assert await live_bus(bridge).wait(0.05) == "reset_all"
    lines = [args[0] for args in env.recs["arena_log"].calls]
    assert any(re.search(r"Reset all: \d+ images re-queued", line) for line in lines)


@pytest.mark.unit
def test_reset_is_undoable(tmp_path):
    """The funnel preserves undo: prime = the last queue edit before the run."""
    env = build_bridge(tmp_path, build_stack([]), n_images=2)
    bridge = env.bridge
    _after_a_run(bridge)
    push_queue_undo(bridge)  # snapshot A: the completed/failed leftovers
    bridge.reset_all()  # snapshot B: all pending
    bridge.undo()
    assert [img.status for img in bridge.state.images] == ["completed", "failed"]


@pytest.mark.unit
def test_reset_image_state_has_no_selection_parameter():
    assert set(inspect.signature(reset_image_state).parameters) == {"img"}
