"""Known-working reference-image transport and required-block gating."""

from types import SimpleNamespace

import pytest

from app.browser.cdp_arena import CDPArenaController, JS_VERIFY_ATTACHMENT
from app.browser.cdp_client import CDPClient
from app.services.single_job_runner import JobCtx, _loop_blocks


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attach_image_cdp_uses_working_branch_selector_order(monkeypatch, tmp_path):
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    client = CDPClient()
    seen = []

    async def document():
        return {"nodeId": 4}

    async def query(root, selector):
        seen.append((root, selector))
        return 9 if selector == 'input[type="file"][accept*="image"]' else None

    async def set_files(node, files):
        seen.append((node, files))
        return True

    monkeypatch.setattr(client, "get_document", document)
    monkeypatch.setattr(client, "query_selector", query)
    monkeypatch.setattr(client, "set_file_input_files", set_files)

    ok, reason = await client.attach_image_cdp(str(image))

    assert ok and "node 9" in reason
    assert seen == [
        (4, 'form input[type="file"][accept*="image"]'),
        (4, 'input[type="file"][accept*="image"]'),
        (9, [str(image.resolve())]),
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_file_input_files_rejects_explicit_cdp_error(monkeypatch):
    client = CDPClient()

    async def failure(_method, _params):
        return {"error": {"code": -32000, "message": "not a file input"}}

    monkeypatch.setattr(client, "send", failure)
    assert await client.set_file_input_files(7, ["/tmp/reference.png"]) is False

    async def success(_method, _params):
        return {"result": {}}

    monkeypatch.setattr(client, "send", success)
    assert await client.set_file_input_files(7, ["/tmp/reference.png"]) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_controller_uses_working_attach_then_preview_retry(monkeypatch, tmp_path):
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    cdp = SimpleNamespace(is_connected=True, attach_image_cdp=_attached,
                          evaluate=_evaluate(iter([{"found": False},
                                                   {"found": True, "matched": "blob"}])))
    controller = CDPArenaController(cdp)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("app.browser.cdp_arena.asyncio.sleep", no_sleep)
    ok, reason = await controller.attach_image(str(image))

    assert ok and reason == "Found via blob"
    assert "div.flex.flex-wrap.gap-2" in JS_VERIFY_ATTACHMENT


@pytest.mark.unit
@pytest.mark.asyncio
async def test_required_attach_failure_stops_before_prompt_and_wait():
    calls = []

    class Ctrl:
        async def attach_image(self, _path):
            calls.append("attach")
            return False, "preview missing"

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
                              display_name="Prompt"),
              SimpleNamespace(block_id="WAIT_OUTPUT", enabled=True, required=True,
                              display_name="Wait")]

    failed, error = await _loop_blocks(ctx, blocks)

    assert failed and "Attach failed" in error
    assert calls == ["attach"]


async def _attached(_path):
    return True, "working transport"


def _evaluate(replies):
    async def evaluate(_script):
        return next(replies)
    return evaluate
