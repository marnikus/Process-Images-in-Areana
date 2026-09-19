"""D4.4: CDPArenaController tests — real CDPClient over a fake websocket.

RULE 8: both the transport (cdp_client) and the controller are real; only the
websockets module is faked, and the "page" is a stateful responder keyed on
the distinctive tokens of each probe JS. The wait-loop paths exercise the
real output_wait module (fast timeouts).
"""

import asyncio
import json

import pytest

from app.browser.cdp_arena import CDPArenaController
from tests.test_cdp_client import make_client

pytestmark = pytest.mark.unit


def _val(x):
    """Runtime.evaluate inner envelope for a JS return value."""
    if x is None:
        return {"result": {"type": "undefined"}}
    t = "string" if isinstance(x, str) else ("boolean" if isinstance(x, bool) else "object")
    return {"result": {"type": t, "value": x}}


class ArenaResponder:
    """Stateful fake page: routes Runtime.evaluate by probe-JS token."""

    def __init__(self):
        self.state = {
            "baseline": {"output_count": 0, "output_srcs": [], "outputs": [], "timestamp": 1},
            "check": {"ready": False, "reason": "waiting"},
            "verify_attachment": {"found": True, "matched": "blob", "alt": "pic.png",
                                  "src": "blob:arena"},
            "insert_prompt": {"ok": True, "len": 10},
            "verify_prompt": {"ok": True, "actual": "hello"},
            "click_send": {"ok": True, "sel": "button[aria-label='Send message']"},
            "send_state": {"found": True, "visible": True, "enabled": True},
            "error_scan": "",
            "page_ready": {"ready": True, "reasons": []},
            "security": False,
            "generating": {"spinning": False, "spinCount": 0, "details": [],
                           "isGenerating": False},
            "download": None,
            "highlight": json.dumps({"rect": {"x": 1, "y": 2, "width": 10, "height": 20}}),
            "watcher_shown": True,
            "dom_doc": {"root": {"nodeId": 5}},
        }
        self.evals = []

    def __call__(self, method, params, server):
        if method != "Runtime.evaluate":
            return self._cdp_command(method, params)
        expr = params.get("expression", "")
        self.evals.append(expr)
        s = self.state
        # Route order matters: check/baseline probe both embed no-scrollbar and
        # animate-spin; the watcher overlay embeds mousedown — most-specific first.
        if '[role="alert"]' in expr:
            return _val(s["error_scan"]), None
        if "oldOutputs" in expr:
            return _val(s["check"]), None
        if "output_srcs" in expr:
            return _val(s["baseline"]), None
        if "tryFetch" in expr:
            return _val(s["download"]), None
        if "no-scrollbar" in expr:
            return _val(s["page_ready"]), None
        if "Security Verification" in expr:
            return _val(s["security"]), None
        if "animate-spin" in expr:
            return _val(s["generating"]), None
        if "===expected" in expr:
            return _val(s["verify_prompt"]), None
        if "HTMLTextAreaElement" in expr:
            return _val(s["insert_prompt"]), None
        if "div.flex.flex-wrap" in expr:
            return _val(s["verify_attachment"]), None
        if "data-arena-watcher" in expr:
            return _val({"shown": s["watcher_shown"]} if "shown" in expr else None), None
        if "mousedown" in expr:
            return _val(s["click_send"]), None
        if "els.length" in expr:
            return _val(s["send_state"]), None
        if "data-arena-highlight" in expr:
            return _val(s["highlight"] if "probe" in expr else {"cleared": 1}), None
        if "window.location.reload" in expr:
            return _val(True), None
        return _val({"ok": True}), None

    def _cdp_command(self, method, params):
        if method == "DOM.getDocument":
            return self.state["dom_doc"], None
        if method == "DOM.querySelector":
            return {"nodeId": 8 if "file" in params.get("selector", "") else 0}, None
        if method == "DOM.setFileInputFiles":
            return {}, None
        return {}, None


@pytest.fixture
def arena(cdp_server):
    responder = ArenaResponder()
    cdp_server.responder = responder
    client = make_client(cdp_server)
    return CDPArenaController(client), client, responder


async def _connected(arena):
    ctrl, client, _ = arena
    assert await client.connect("ws://127.0.0.1:9222/devtools/page/t1") is True
    return ctrl


# ── basics ──

async def test_ensure_connected(arena):
    ctrl, client, _ = arena
    assert await ctrl.ensure_connected() is False
    await client.connect("ws://127.0.0.1:9222/devtools/page/t1")
    assert await ctrl.ensure_connected() is True


async def test_log_callback_and_swallowed_errors(arena):
    ctrl, _, _ = arena
    seen = []
    ctrl.set_log_callback(seen.append)
    ctrl.report("hello", "info")
    assert seen == ["hello"]

    class Boom:
        def __call__(self, msg):
            raise RuntimeError("cb")
    ctrl.set_log_callback(Boom())
    ctrl.report("swallowed")  # must not raise


async def test_capture_baseline(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    baseline = await ctrl.capture_baseline()
    assert baseline["output_srcs"] == [] and baseline["timestamp"] == 1
    resp.state["baseline"] = None
    default = await ctrl.capture_baseline()  # evaluate → None → default shape
    assert default == {"output_count": 0, "output_srcs": [], "timestamp": default["timestamp"]}


# ── attach / verify / prompt / submit ──

async def test_attach_image_success_and_not_connected(arena, tmp_path):
    ctrl, client, _ = arena
    assert await client.connect("ws://127.0.0.1:9222/devtools/page/t1") is True
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")
    ok, reason = await ctrl.attach_image(str(img))  # CDP attach + verify (blob)
    assert ok is True and "blob" in reason
    client._connected = False
    ok, reason = await ctrl.attach_image(str(img))
    assert ok is False and reason == "Not connected"


async def test_attach_image_cdp_failure(arena, tmp_path):
    ctrl = await _connected(arena)
    resp = arena[2]
    resp.state["dom_doc"] = {"root": {}}  # no root nodeId → attach fails fast
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")
    ok, reason = await ctrl.attach_image(str(img))
    assert ok is False and "document root" in reason.lower()


async def test_verify_attachment_not_found(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    resp.state["verify_attachment"] = {"found": False}
    ok, reason = await ctrl.verify_attachment("pic.png")
    assert ok is False and "Not found" in reason


async def test_insert_prompt_paths(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    ok, reason = await ctrl.insert_prompt("make a cat")
    assert ok is True and "len 10" in reason
    resp.state["insert_prompt"] = {"ok": False, "error": "textarea hidden"}
    ok, reason = await ctrl.insert_prompt("make a cat")
    assert ok is False and reason == "textarea hidden"
    resp.state["insert_prompt"] = None
    ok, reason = await ctrl.insert_prompt("make a cat")
    assert ok is False and reason == "No result"


async def test_verify_prompt(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    assert (await ctrl.verify_prompt("hello")) == (True, "Exact match")
    resp.state["verify_prompt"] = {"ok": False, "actual": "other"}
    ok, reason = await ctrl.verify_prompt("hello")
    assert ok is False and "Mismatch" in reason


async def test_submit_and_not_connected(arena):
    ctrl, client, _ = arena
    assert await client.connect("ws://127.0.0.1:9222/devtools/page/t1") is True
    ok, reason = await ctrl.submit()
    assert ok is True and reason == "Clicked"
    client._connected = False
    assert (await ctrl.submit()) == (False, "Not connected")


async def test_submit_when_ready_states(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    ok, reason = await ctrl.submit_when_ready(timeout_sec=0.2)
    assert ok is True and reason == "Clicked"
    for state, expected in [
        ({"found": False, "visible": False, "enabled": False}, "send not found"),
        ({"found": True, "visible": False, "enabled": False}, "send hidden"),
        ({"found": True, "visible": True, "enabled": False}, "send disabled"),
    ]:
        resp.state["send_state"] = state
        ok, reason = await ctrl.submit_when_ready(timeout_sec=0.2)
        assert ok is False and reason == expected


# ── page errors / state probes ──

async def test_scan_page_errors(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    resp.state["error_scan"] = "Something went wrong"
    assert await ctrl.scan_page_errors() == "Something went wrong"
    resp.state["error_scan"] = None
    assert await ctrl.scan_page_errors() == ""


async def test_page_state_probes(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    ready, reasons = await ctrl.is_page_ready()
    assert ready is True and reasons == []
    resp.state["page_ready"] = {"ready": False, "reasons": ["send not found"]}
    ready, reasons = await ctrl.is_page_ready()
    assert ready is False and reasons == ["send not found"]
    assert await ctrl.is_security_dialog_visible() is False
    resp.state["security"] = True
    assert await ctrl.is_security_dialog_visible() is True
    gen, info = await ctrl.is_generating()
    assert gen is False
    resp.state["generating"] = {"spinning": True, "spinCount": 1, "details": [],
                                "isGenerating": True}
    gen, info = await ctrl.is_generating()
    assert gen is True and info["spinCount"] == 1
    resp.state["check"] = {"spinning": False}
    assert (await ctrl.get_generation_state())["spinning"] is False


# ── wait_for_new_output ──

async def test_wait_completed_with_recheck(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    resp.state["check"] = {"ready": True, "src": "blob:new.png",
                           "rect": {"x": 0, "y": 0, "width": 100, "height": 50}}
    status, data = await ctrl.wait_for_new_output(
        {"output_srcs": ["blob:old"], "outputs": []}, timeout_ms=10000)
    assert status == "completed" and data["new_src"] == "blob:new.png"
    assert data["baseline"]["output_srcs"] == ["blob:old"]


async def test_wait_cancelled(arena):
    ctrl = await _connected(arena)
    status, data = await ctrl.wait_for_new_output(
        {"output_srcs": []}, timeout_ms=60000, cancel_check=lambda: True)
    assert status == "failed" and data.get("cancelled") is True


async def test_wait_fails_fast_on_existing_error(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    resp.state["error_scan"] = "Rate limit exceeded"
    status, data = await ctrl.wait_for_new_output({"output_srcs": []}, timeout_ms=60000)
    assert status == "failed" and "Rate limit" in data["error"]


async def test_wait_times_out_and_settles_security_gate(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    settled = []
    ctrl.security_settler = lambda: settled.append(True)
    resp.state["security"] = True
    status, data = await ctrl.wait_for_new_output({"output_srcs": []}, timeout_ms=400)
    assert status == "failed" and "Timeout" in data["error"]
    assert len(settled) >= 1  # security gate ran inside the wait loop


# ── download ──

async def test_download_image_js_success(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    resp.state["download"] = {"ok": True, "bytes": [137, 80, 78, 71] * 50,
                              "contentType": "image/png"}
    ok, data, ctype = await ctrl.download_image("blob:arena/img.png")
    assert ok is True and len(data) == 200 and ctype == "image/png"


class _FakeHttpResp:
    def __init__(self, body, ctype="image/png"):
        self._body, self._ctype = body, ctype

    def read(self):
        return self._body

    @property
    def headers(self):
        return {"Content-Type": self._ctype,
                "get": lambda k, d="": self._ctype if k == "Content-Type" else d}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


async def test_download_image_python_fallback_paths(arena, monkeypatch):
    import urllib.request
    ctrl = await _connected(arena)
    resp = arena[2]
    logs = []
    ctrl.set_log_callback(logs.append)  # stage details land in the log
    resp.state["download"] = {"ok": False, "error": "cors denied", "method": "fetch"}

    good = b"\x89PNG" + b"x" * 300
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None, context=None: _FakeHttpResp(good))
    ok, data, ctype = await ctrl.download_image("https://arena.ai/out/1.png")
    assert ok is True and data == good and ctype == "image/png"

    html_body = b"<!DOCTYPE html><html><head><meta charset='utf-8'><title>login</title></head><body>sign in first please</body></html>"
    assert len(html_body) > 100  # size check runs before the HTML sniff
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None, context=None: _FakeHttpResp(html_body))
    ok, _, err = await ctrl.download_image("https://arena.ai/out/2.png")
    # wire message is the collapse; the HTML sniff detail goes to the log
    assert ok is False and "All methods failed" in err
    assert any("HTML page" in m for m in logs)

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None, context=None: _FakeHttpResp(b"small"))
    ok, _, err = await ctrl.download_image("https://arena.ai/out/3.png")
    assert ok is False and any("Too small" in m for m in logs)

    def boom(req, timeout=None, context=None):
        raise OSError("network down")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    ok, _, err = await ctrl.download_image("https://arena.ai/out/4.png")
    assert ok is False and "All methods failed" in err
    assert any("Python download failed" in m for m in logs)


# ── highlight / overlay / reload ──

async def test_highlight_selector_and_clear(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    rect = await ctrl.highlight_selector("textarea[name='message']", color="#00AAFF",
                                         duration_ms=500, caption="Prompt")
    assert rect == {"x": 1, "y": 2, "width": 10, "height": 20}  # probe JSON parsed
    resp.state["highlight"] = None  # probe + legacy both empty → default rect
    assert await ctrl.highlight_selector("div") == {"x": 100, "y": 100, "width": 200, "height": 100}
    await ctrl.clear_highlights()  # must not raise
    assert any("querySelectorAll" in e for e in resp.evals)


async def test_watcher_overlay_show_hide(arena):
    ctrl = await _connected(arena)
    resp = arena[2]
    assert await ctrl.show_watcher_overlay("waiting", kind="generation",
                                           timeout_sec=60, sub="s") is True
    resp.state["watcher_shown"] = False
    assert await ctrl.show_watcher_overlay("waiting") is False
    assert await ctrl.hide_watcher_overlay() is True


async def test_reload_page_ready(arena):
    ctrl = await _connected(arena)
    ok, reason = await ctrl.reload_page()  # Page.reload → 4s settle → ready
    assert ok is True and reason == "Reloaded and ready"
