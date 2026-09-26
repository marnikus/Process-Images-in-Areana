"""D4.4: CDPArenaController tests — real CDPClient over a fake websocket.

RULE 8: both the transport (cdp_client) and the controller are real; only the
websockets module is faked, and the "page" is a stateful responder keyed on
the distinctive tokens of each probe JS. The wait-loop paths exercise the
real output_wait module (fast timeouts).
"""

import asyncio
import base64
import json
import re
import time

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
        self.b64, self.freed, self.slices = "", False, 0

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
        if "__arenaDl" in expr:
            return _val(self._slot(expr)), None
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

    def _slot(self, expr):
        """The sliced page download: fetch-to-slot meta, slices, free (2026-09-26)."""
        if "viaCanvas" in expr:
            data = self.state["download"]
            if data is None:
                return {"ok": False, "error": "fetch: TypeError: Failed to fetch"}
            self.b64 = base64.b64encode(data).decode()
            return {"ok": True, "size": len(data), "b64len": len(self.b64),
                    "contentType": "image/png", "method": "fetch"}
        if "delete window.__arenaDl" in expr:
            self.freed = True
            return True
        start, count = (int(x) for x in re.findall(r", (\d+), (\d+)\)$", expr)[0])
        self.slices += 1
        return self.b64[start:start + count]

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
    assert "captcha wait" not in data["error"]  # no clock installed ⇒ no pause, no note


async def test_settle_inside_the_wait_is_charged_to_the_pause_clock(arena):
    """S3 / I-52: the settle's duration is absorbed — a wait shorter than the
    settle still times out only after the *paused* elapsed passes the timeout,
    and the failure text carries the evidence."""
    from app.core.pause_clock import PauseClock
    ctrl = await _connected(arena)
    resp = arena[2]
    resp.state["security"] = True
    async def slow_settle():
        await asyncio.sleep(0.3)
        resp.state["security"] = False  # the dialog clears after one settle

    ctrl.security_settler = slow_settle
    ctrl.pause_clock = PauseClock(cap_s=300)
    t0 = time.monotonic()
    status, data = await ctrl.wait_for_new_output({"output_srcs": []}, timeout_ms=400)
    wall = time.monotonic() - t0
    assert status == "failed" and "Timeout after 400ms" in data["error"]
    assert ctrl.pause_clock.total >= 0.3  # the settle was charged
    assert wall >= 0.4 + 0.3  # the wait outlived timeout + the absorbed settle
    assert "captcha wait" in data["error"]  # `_timeout_text` carried the note
    assert data["last_check"]["paused_s"] == ctrl.pause_clock.total


# ── download ──

async def test_download_blob_src_is_pulled_in_slices_and_the_slot_freed(arena, monkeypatch):
    """2026-09-26: a blob: src cannot be fetched from Python — the page copies it
    into a window slot and Python reads it in slices (never one giant reply)."""
    from app.browser.cdp_arena import download
    monkeypatch.setattr(download, "CHUNK_CHARS", 64)
    ctrl = await _connected(arena)
    resp = arena[2]
    resp.state["download"] = b"\x89PNG" + bytes(range(256)) * 2
    ok, data, ctype = await ctrl.download_image("blob:arena/img.png")
    assert ok is True and data == resp.state["download"] and ctype == "image/png"
    assert resp.slices == -(-len(resp.b64) // 64) and resp.slices > 5
    assert resp.freed is True


class _FakeHttpResp:
    def __init__(self, body, ctype="image/png"):
        self._body, self._ctype = body, ctype

    def read(self):
        return self._body

    @property
    def headers(self):
        return {"Content-Type": self._ctype}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


async def test_download_https_src_is_fetched_by_python_first(arena, monkeypatch):
    import urllib.request
    ctrl = await _connected(arena)
    resp = arena[2]
    good = b"\x89PNG" + b"x" * 300
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeHttpResp(good))
    ok, data, ctype = await ctrl.download_image("https://arena.ai/out/1.png")
    assert ok is True and data == good and ctype == "image/png"
    assert not any("__arenaDl" in e for e in resp.evals)  # no DevTools traffic at all


@pytest.mark.parametrize("body,needle", [
    (b"<!DOCTYPE html><html><head><title>login</title></head><body>sign in first please</body></html>", "HTML page"),
    (b"small", "only 5 bytes"),
])
async def test_download_python_refusal_falls_back_to_the_page(arena, monkeypatch, body, needle):
    import urllib.request
    ctrl = await _connected(arena)
    resp = arena[2]
    logs = []
    ctrl.set_log_callback(logs.append)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeHttpResp(body))
    resp.state["download"] = b"\x89PNG" + b"y" * 300
    ok, data, _ctype = await ctrl.download_image("https://arena.ai/out/2.png")
    assert ok is True and data == resp.state["download"] and resp.freed
    assert any(needle in m and "trying the page" in m for m in logs)


async def test_download_names_every_method_when_all_fail(arena, cdp_server, monkeypatch):
    """B8 kept: the page's empty answer is named — now next to Python's reason."""
    import urllib.request
    ctrl = await _connected(arena)
    resp = arena[2]

    def gone_mid_download(method, params, server):
        if method == "Runtime.evaluate" and "__arenaDl" in params.get("expression", ""):
            return None, {"code": -32000, "message": "Execution context was destroyed."}
        return resp(method, params, server)
    cdp_server.responder = gone_mid_download

    def boom(req, timeout=None):
        raise OSError("network down")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    ok, _, err = await ctrl.download_image("https://arena.ai/out/9.png")
    assert ok is False and err.startswith("All methods failed for https://arena.ai/out/9.png")
    assert "Python download failed: download failed: network down" in err
    assert "No result (Execution context was destroyed.)" in err


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
