"""The new-chat verdict a job asks before it starts (I-74, owner request 2026-09-27)."""
import json

import pytest

from app.browser import chat_page as cp

pytestmark = pytest.mark.unit

FRESH = {"path": "/image/direct", "messages": 0, "outputs": 0, "attachments": 0, "composer": 0}


def test_a_fresh_new_chat_is_new_as_a_dict_or_as_its_json_text():
    assert cp.verdict(FRESH) == (True, "new chat")
    assert cp.verdict(json.dumps(FRESH)) == (True, "new chat")
    assert cp.verdict("not json")[0] is None


@pytest.mark.parametrize("change, words", [
    ({"path": "/c/01a0e496-deff"}, "a started chat (/c/01a0e496-deff)"),
    ({"messages": 2}, "2 message(s) on the page"),
    ({"outputs": 1}, "1 generated image(s) on the page"),
    ({"composer": 12}, "the prompt box holds 12 characters"),
    ({"composer": -1}, "no prompt box"),
    ({"attachments": 1}, "1 attached file(s)"),
])
def test_each_piece_of_evidence_is_named(change, words):
    assert cp.verdict({**FRESH, **change}) == (False, words)


def test_several_pieces_are_all_named_in_page_order():
    state = {**FRESH, "path": "/c/x", "messages": 1, "outputs": 1}
    assert cp.verdict(state) == (False, "a started chat (/c/x), 1 message(s) on the page, "
                                        "1 generated image(s) on the page")


@pytest.mark.parametrize("raw", [None, "", [], {"error": "TypeError: x"}, {"messages": 0}])
def test_an_unreadable_answer_is_unknown_not_new(raw):
    is_new, why = cp.verdict(raw)
    assert is_new is None and why.startswith("the page did not say")


class Client:
    def __init__(self, answer, error=""):
        self.answer, self.timeouts = answer, []
        self.last_error, self.last_error_kind = error, "transport" if error else ""

    async def evaluate(self, js, await_promise=True, timeout=30.0):
        self.timeouts.append(timeout)
        return self.answer


async def test_reading_the_page_is_one_5s_check():
    client = Client(FRESH)
    assert await cp.read_chat_page(client) == (True, "new chat")
    assert client.timeouts == [5.0]


async def test_a_page_that_does_not_answer_is_unknown_with_the_transport_reason():
    client = Client(None, "TimeoutError: CDP command Runtime.evaluate timed out after 5.0s")
    is_new, why = await cp.read_chat_page(client)
    assert is_new is None
    assert why == "the page did not say (TimeoutError: CDP command Runtime.evaluate timed out after 5.0s)"


def test_the_probe_carries_the_adapter_selectors_not_placeholders():
    js = cp.build_chat_page_js()
    assert "__" not in js
    assert 'textarea[name=\\"message\\"]' in js or 'textarea[name="message"]' in js
    assert "cloudflarestorage" in js and "self-end" in js


async def test_a_client_that_raises_is_unknown_not_a_crash():
    is_new, why = await cp.read_chat_page(None)
    assert is_new is None and why.startswith("the page did not say (AttributeError:")
