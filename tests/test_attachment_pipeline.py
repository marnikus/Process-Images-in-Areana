"""Reference-image attachment targets and verifies the active composer."""

from types import SimpleNamespace

import pytest

from app.browser.attachment_probes import AttachmentEvidence, attach_file
from app.browser.cdp_arena import CDPArenaController
from app.browser.cdp_client import CDPClient
from app.services.single_job_runner import JobCtx, _loop_blocks


class AttachmentCDP:
    def __init__(self, set_ok=True):
        self.set_ok = set_ok
        self.evaluated = []
        self.selected = []

    async def evaluate(self, script):
        self.evaluated.append(script)
        if "visible prompt composer not found" in script:
            return {"ok": True, "marker": "marker", "previews": ["blob:old|"],
                    "prompt": "message"}
        return {"ok": True, "removed": True}

    async def get_document(self):
        return {"nodeId": 1}

    async def query_selector(self, root_id, selector):
        self.selected.append((root_id, selector))
        return 9

    async def set_file_input_files(self, node_id, files):
        self.selected.append((node_id, files))
        return self.set_ok


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attach_file_marks_active_input_and_always_cleans_up(tmp_path):
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    cdp = AttachmentCDP(set_ok=True)

    evidence = await attach_file(cdp, str(image))

    assert evidence.ok and evidence.previews == ("blob:old|",)
    assert cdp.selected[0] == (1, '[data-arena-upload-target="marker"]')
    assert cdp.selected[1] == (9, [str(image)])
    assert "removeAttribute" in cdp.evaluated[-1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attach_file_rejects_missing_path_and_protocol_failure(tmp_path):
    missing = await attach_file(AttachmentCDP(), str(tmp_path / "missing.png"))
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    failed = await attach_file(AttachmentCDP(set_ok=False), str(image))

    assert not missing.ok and "not a file" in missing.reason
    assert not failed.ok and "protocol error" in failed.reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_file_input_files_rejects_cdp_error(monkeypatch):
    client = CDPClient()

    async def send(_method, _params):
        return {"error": {"code": -32000, "message": "Node is not a file input"}}

    monkeypatch.setattr(client, "send", send)
    assert await client.set_file_input_files(7, ["/tmp/reference.png"]) is False

    async def success(_method, _params):
        return {"result": {}}

    monkeypatch.setattr(client, "send", success)
    assert await client.set_file_input_files(7, ["/tmp/reference.png"]) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_controller_requires_active_composer_evidence(monkeypatch, tmp_path):
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    cdp = SimpleNamespace(is_connected=True)
    controller = CDPArenaController(cdp)
    monkeypatch.setattr("app.browser.cdp_arena.attach_file", lambda *_: _evidence())

    async def no_sleep(_delay):
        return None
    monkeypatch.setattr("app.browser.cdp_arena.asyncio.sleep", no_sleep)
    replies = iter([{"found": False}, {"found": True, "matched": "new-active-preview"}])
    cdp.evaluate = _evaluate(replies)

    ok, reason = await controller.attach_image(str(image))

    assert ok and "new-active-preview" in reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_required_attach_failure_stops_before_prompt_and_wait():
    calls = []

    class Ctrl:
        async def attach_image(self, _path):
            calls.append("attach")
            return False, "active composer input missing"

        async def insert_prompt(self, _text):
            calls.append("prompt")
            return True, "inserted"

    bridge = SimpleNamespace(_cancel_requested=False,
                             _emit_job_action_status=lambda *_: None)
    ctx = JobCtx(bridge=bridge, ctrl=Ctrl(), client=None, tab_id="t1",
                 img=SimpleNamespace(absolute_path="/tmp/reference.png"), urls=[],
                 job_id="j1", corr_id="c1", final_prompt="describe it")
    blocks = [SimpleNamespace(block_id="ATTACH_IMAGE", enabled=True, required=True,
                              display_name="Attach"),
              SimpleNamespace(block_id="INSERT_PROMPT", enabled=True, required=True,
                              display_name="Prompt")]

    failed, error = await _loop_blocks(ctx, blocks)

    assert failed and "Attach failed" in error
    assert calls == ["attach"]


async def _evidence():
    return AttachmentEvidence(True, "set", ("blob:old|",))


def _evaluate(replies):
    async def evaluate(_script):
        return next(replies)
    return evaluate
