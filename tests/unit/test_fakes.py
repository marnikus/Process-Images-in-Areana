"""Unit tests for fakes — ensure fake adapters work fast, no real Chrome/Qt (Phase 2).

RULE 18: file 60-200 LOC.
"""

import pytest

from tests.fakes.fake_bridge import FakeBridge
from tests.fakes.fake_cdp import FakeCDPClient, FakeCDPTransport
from tests.fakes.fake_arena import FakeArenaController
from tests.fakes.fake_runner import FakeActionRunner


@pytest.mark.unit
def test_fake_bridge_pure():
    bridge = FakeBridge()
    bridge.log("hello", "info")
    bridge.emit_state({"images": []})
    assert len(bridge.get_logs()) == 1
    assert len(bridge.get_states()) == 1


@pytest.mark.unit
def test_fake_cdp_transport_pure():
    transport = FakeCDPTransport()
    assert transport.is_connected is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fake_cdp_client_pure():
    client = FakeCDPClient()
    ok, msg = await client.attach_image_cdp("/tmp/test.png")
    assert ok is True
    assert "Fake attached" in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fake_arena_controller_pure():
    ctrl = FakeArenaController(baseline_count=1, new_src="https://a.com/new.png")
    base = await ctrl.capture_baseline()
    assert base["output_count"] == 1
    ok, _ = await ctrl.attach_image("/tmp/a.png")
    assert ok is True
    assert ctrl.get_attached() == ["/tmp/a.png"]
    ok, _ = await ctrl.insert_prompt("hello")
    assert ok is True
    status, data = await ctrl.wait_for_new_output(base, correlation_id="J1")
    assert status == "completed"
    assert data["new_src"] == "https://a.com/new.png"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fake_runner_pure():
    runner = FakeActionRunner(results={"ATTACH_IMAGE": "ok", "SUBMIT": "fail"})
    res = await runner.run_block("ATTACH_IMAGE")
    assert res["ok"] is True
    res2 = await runner.run_block("SUBMIT")
    assert res2["ok"] is False
    assert runner.get_executed() == ["ATTACH_IMAGE", "SUBMIT"]
