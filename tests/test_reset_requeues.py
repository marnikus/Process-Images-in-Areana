"""S4 · D-6R — every reset re-queues: `pending` **and** `selected=True`, the
change goes through the one funnel (`commit_queue`), wakes the live bus, is
counted in the log, and is undoable. Real `Bridge` from the golden harness.

RED at base: `selected is False` after `reset_all()` (`reset_image_state(img, False)`).
"""

import inspect
import json
import re

import pytest

from app.services.live.bus import live_bus
from app.services.live.feed import eligible_images
from app.ui.panels import run_control
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit


def finished_bridge(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=3)
    bridge = env.bridge
    statuses = ("completed", "failed", "skipped")
    for img, status in zip(bridge.state.images, statuses):
        img.status, img.selected, img.error = status, False, "boom" if status == "failed" else None
        img.attempt_count, img.output_path = 2, f"/out/{img.filename}"
    bridge.state.recalculate_progress()
    return env, bridge


def logged(env):
    return [m for m, _lvl in env.recs["arena_log"].calls]


def test_reset_all_requeues_every_image_selected(tmp_path):
    env, bridge = finished_bridge(tmp_path)
    res = json.loads(bridge.reset_all())
    assert res["ok"] is True and res["count"] == 3
    for img in bridge.state.images:
        assert (img.status, img.selected) == ("pending", True)
        assert img.error is None and img.attempt_count == 0 and img.output_path is None
    assert len(eligible_images(bridge.state.images)) == 3
    assert bridge.state.progress["pending"] == 3


def test_reset_image_requeues_that_image_selected(tmp_path):
    env, bridge = finished_bridge(tmp_path)
    target = bridge.state.images[0]
    assert json.loads(bridge.reset_image(target.id))["ok"] is True
    assert (target.status, target.selected) == ("pending", True)
    others = bridge.state.images[1:]
    assert all(i.status != "pending" and i.selected is False for i in others)  # only the one row
    assert eligible_images(bridge.state.images) == [target]


@pytest.mark.asyncio
async def test_reset_wakes_the_loop_and_logs_the_count(tmp_path):
    env, bridge = finished_bridge(tmp_path)
    bridge.reset_all()
    assert await live_bus(bridge).wait(0.05) == "reset_all"
    lines = [m for m in logged(env) if re.search(r"Reset all: \d+ images re-queued", m)]
    assert len(lines) == 1 and "3 images" in lines[0]
    bridge.reset_image(bridge.state.images[1].id)
    assert await live_bus(bridge).wait(0.05) == "reset_image"
    assert any(re.search(r"Reset .*re-queued", m) for m in logged(env)[len(lines):])


def test_reset_is_undoable(tmp_path):
    env, bridge = finished_bridge(tmp_path)
    before = [(i.status, i.selected) for i in bridge.state.images]
    bridge.undo_service.push("queue", [{"id": i.id, "status": i.status, "selected": i.selected}
                                       for i in bridge.state.images])  # the state the user had
    bridge.reset_all()
    assert all(i.status == "pending" for i in bridge.state.images)
    bridge.undo()
    assert [(i.status, i.selected) for i in bridge.state.images] == before


def test_reset_image_state_has_no_selection_parameter():
    """Signature lock: `False` can never be passed again."""
    params = list(inspect.signature(run_control.reset_image_state).parameters)
    assert params == ["img"]


def test_retry_paths_use_the_same_funnel(tmp_path):
    env, bridge = finished_bridge(tmp_path)
    failed = [i for i in bridge.state.images if i.status == "failed"]
    assert json.loads(bridge.retry_failed())["count"] == 1
    assert (failed[0].status, failed[0].selected) == ("pending", True)
    assert live_bus(bridge).reasons() == ["retry_failed"]
    skipped = [i for i in bridge.state.images if i.status == "skipped"][0]
    assert json.loads(bridge.retry_image(skipped.id))["ok"] is True
    assert (skipped.status, skipped.selected) == ("pending", True)
    assert live_bus(bridge).reasons() == ["retry_failed", "retry_image"]
