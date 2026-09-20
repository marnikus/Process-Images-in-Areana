# ideal-size: ~130 lines reason=S4 RED budget — real-Bridge D-6R contract (tdd-interfaces rev-3, 5 tests)
"""D-6R end-to-end on a REAL Bridge — every reset re-queues.

Both resets return images to `pending` AND `selected=True`, log a count
line, wake the live bus, and stay undoable. `reset_image_state` loses its
`selected` parameter entirely (signature lock).
"""

import asyncio
import inspect
import json
import re

from app.ui.panels.run_control import reset_image_state
from tests.characterization.harness import build_bridge


def test_eligible_images_returns_all_of_them(tmp_path):
    from app.core.run_scope import eligible_images  # the one rule (merge-note §2)

    ns = build_bridge(tmp_path, stack=[], n_images=5)
    bridge = ns.bridge
    statuses = ["pending", "failed", "selected", "needs_review", "processing"]
    for img, status in zip(bridge.state.images, statuses):
        img.status = status
        img.selected = True
    bridge.state.images[4].selected = False  # deselected is never eligible
    got = eligible_images(bridge.state.images)
    assert [img.status for img in got] == ["pending", "failed", "selected", "needs_review"]


def test_reset_image_requeues(tmp_path):
    ns = build_bridge(tmp_path, stack=[], n_images=1)
    img = ns.bridge.state.images[0]
    img.status = "completed"
    img.selected = False
    img.error = "ancient"

    assert list(inspect.signature(reset_image_state).parameters) == ["img"]  # param deleted (D-6R)
    result = ns.bridge.reset_image(img.id)

    assert json.loads(result)["ok"] is True
    assert img.status == "pending"
    assert img.selected is True  # D-6R: reset re-queues, it does not park
    assert img.error is None


def test_reset_all_requeues_and_logs(tmp_path):
    ns = build_bridge(tmp_path, stack=[], n_images=2)
    for img in ns.bridge.state.images:
        img.status = "failed"
        img.selected = False

    ns.bridge.reset_all()

    for img in ns.bridge.state.images:
        assert img.status == "pending"
        assert img.selected is True
    logs = " ".join(str(call) for call in ns.recs["arena_log"].calls)
    assert re.search(r"Reset [Aa]ll: \d+ images re-queued", logs)


def test_reset_is_undoable(tmp_path):
    ns = build_bridge(tmp_path, stack=[], n_images=1)
    bridge = ns.bridge
    img = bridge.state.images[0]
    img.status = "completed"
    img.selected = False
    bridge.set_image_selected(img.id, True)  # snapshot BEFORE the reset
    bridge.reset_image(img.id)
    assert img.status == "pending"

    bridge.undo_service.undo()

    assert img.status == "completed"  # reset undone — work not lost


def test_reset_all_wakes_live_loop(tmp_path):
    from app.services.live.bus import live_bus  # S4 module — RED until it exists

    ns = build_bridge(tmp_path, stack=[], n_images=1)
    bridge = ns.bridge

    async def main(loop):
        bus = live_bus(bridge)
        bus.attach(loop)
        task = asyncio.ensure_future(bus.wait(2.0))
        await asyncio.sleep(0.02)
        await asyncio.to_thread(bridge.reset_all)
        return await asyncio.wait_for(task, 3.0)

    loop = asyncio.new_event_loop()
    try:
        reason = loop.run_until_complete(main(loop))
    finally:
        loop.close()
    assert "reset_all" in reason
