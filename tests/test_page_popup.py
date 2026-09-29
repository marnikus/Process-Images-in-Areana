"""The page's own new tab (`window.open`) — the profile-locked opener (I-79 v5).

A CDP `Target.createTarget` cannot reach a regular Chrome profile context (design §4), but a
page can only open a tab into its *own* profile. Design:
docs/archive/2026-09-29-new-chat-new-tab-profile-truth/design.md §3 R3(b).
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest

from app.browser import page_popup

pytestmark = pytest.mark.unit

URL = "https://arena.ai/image/direct?model_a=max"


def test_the_payload_opens_the_url_in_the_pages_own_profile():
    js = page_popup.build_open_tab_js(URL)
    assert "window.open(" in js and "_blank" in js
    literal = json.loads(re.search(r'const url = ("(?:[^"\\]|\\.)*")', js).group(1))
    assert literal == URL


def test_the_url_is_embedded_as_a_json_literal():
    raw = 'https://x/?a="b"\\c\n'
    js = page_popup.build_open_tab_js(raw)
    literal = json.loads(re.search(r'const url = ("(?:[^"\\]|\\.)*")', js).group(1))
    assert literal == raw
    line = next(ln for ln in js.splitlines() if "const url" in ln)
    assert json.dumps(raw) in line       # escaped form: quotes/backslash/newline survive as text


class _Client:
    """Page-level CDP client stand-in: answers Runtime.evaluate Chrome-style."""

    def __init__(self, value=None, error=None, boom=None):
        self.value, self.error, self.boom = value, error, boom
        self.sent = []

    async def send(self, method, params=None, timeout=30):
        self.sent.append((method, params))
        if self.boom:
            raise self.boom
        if self.error:
            return {"id": 1, "error": {"message": self.error}}
        return {"id": 1, "result": {"result": {"type": "object", "value": self.value}}}


def _run(client, url=URL):
    return asyncio.run(page_popup.open_tab_via_page(client, url, timeout_sec=2.0))


def test_an_opened_tab_answers_ok_and_marks_the_call_a_user_gesture():
    client = _Client(value={"ok": True})
    assert _run(client) == (True, "")
    method, params = client.sent[0]
    assert method == "Runtime.evaluate" and params["userGesture"] is True
    assert params["returnByValue"] is True and params["awaitPromise"] is True


def test_a_blocked_popup_is_a_reason_with_the_pages_own_words():
    client = _Client(value={"ok": False, "error": "window.open returned null (popup blocked)"})
    ok, why = _run(client)
    assert ok is False and "popup blocked" in why


def test_an_empty_answer_from_the_page_is_no_proof():
    assert _run(_Client(value=None))[0] is False
    assert _run(_Client(value="yes"))[0] is False


def test_an_answer_of_the_wrong_shape_is_no_proof():
    class _Odd:
        async def send(self, method, params=None, timeout=30):
            return {"id": 1, "result": "weird"}          # not a Runtime.evaluate payload
    assert asyncio.run(page_popup.open_tab_via_page(_Odd(), URL, timeout_sec=1.0))[0] is False
    assert _run(_Client(value={"ok": True, "via": "flat"})) == (True, "")   # flat value also read


def test_a_reply_that_is_not_a_message_is_no_proof():
    class _Junk:
        async def send(self, method, params=None, timeout=30):
            return ["nope"]
    ok, why = asyncio.run(page_popup.open_tab_via_page(_Junk(), URL, timeout_sec=1.0))
    assert ok is False and "no answer" in why


def test_a_protocol_error_and_a_dead_socket_are_reasons():
    ok, why = _run(_Client(error="Target closed"))
    assert ok is False and "Target closed" in why
    ok, why = _run(_Client(boom=RuntimeError("not connected")))
    assert ok is False and "not connected" in why
