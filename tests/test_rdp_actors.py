"""RDP packet shapes — the pure parsers, pinned against real Firefox replies.

Every function here is a pure function over a decoded packet, which is exactly
why the shapes a browser version can send are pinned by tests instead of hoped
for: a descriptor without a `browsingContextID`, a form without a `consoleActor`,
a value that came back as a long string, an error packet on the reply slot.

The rule the parsers keep: **skip what is unknown, never guess** — a row that
cannot be a tab is dropped, and a reply that is not a verdict is not read as one.

RED at `464185a`: `app.browser.rdp` did not exist.
"""

import pytest

from app.browser import protocols
from app.browser.rdp import actors, wire

pytestmark = pytest.mark.unit

DESCRIPTOR = {"actor": "server1.conn2.tabDescriptor1", "browserId": 2, "browsingContextID": 3,
              "outerWindowID": 6, "isZombieTab": False, "selected": True,
              "title": "Arena", "url": "https://arena.ai/c/1",
              "traits": {"watcher": True}}


# ── field readers ──


def test_text_and_int_fields_survive_missing_and_hostile_values():
    assert actors.text_field(DESCRIPTOR, "title") == "Arena"
    assert actors.text_field(DESCRIPTOR, "nope") == ""
    assert actors.text_field(None, "title") == ""
    assert actors.int_field(DESCRIPTOR, "browsingContextID") == 3
    assert actors.int_field(DESCRIPTOR, "nope") == 0
    assert actors.int_field({"outerWindowID": "not-a-number"}, "outerWindowID") == 0


def test_a_tab_id_is_the_browsing_context_and_survives_a_string():
    assert actors.tab_id(3) == "ctx-3"
    assert actors.tab_id("17") == "ctx-17"
    assert actors.tab_id("about:blank") == "ctx-about:blank", "an unparsable id is still stable"


# ── descriptors ──


def test_a_descriptor_becomes_a_tab_with_its_browser_context_identity():
    tab = actors.tab_of_descriptor(DESCRIPTOR)
    assert (tab.id, tab.actor) == ("ctx-3", "server1.conn2.tabDescriptor1")
    assert tab.title == "Arena" and tab.url == "https://arena.ai/c/1"
    assert tab.browser_id == 2 and tab.outer_window_id == 6
    assert tab.selected is True and tab.is_zombie is False and tab.traits == {"watcher": True}
    assert tab.protocol == "rdp" and tab.ws_url == ""


def test_a_row_that_cannot_be_a_tab_is_dropped_never_guessed():
    assert actors.tab_of_descriptor(None) is None
    assert actors.tab_of_descriptor({"title": "no actor, no context"}) is None
    assert actors.tab_of_descriptor({"actor": ""}) is None
    tab = actors.tab_of_descriptor({"actor": "server1.conn2.tabDescriptor9"})
    assert tab.id == "ctx-server1.conn2.tabDescriptor9", "an actor-only row still gets a handle"


def test_tabs_in_reads_the_listtabs_reply_and_skips_junk_rows():
    reply = {"from": "root", "tabs": [DESCRIPTOR, "junk", {"title": "no identity"}, None]}
    tabs = actors.tabs_in(reply)
    assert [t.id for t in tabs] == ["ctx-3"], "one real tab, junk skipped"
    assert actors.tabs_in({}) == []
    assert actors.tabs_in({"tabs": "not a list"}) == []
    assert actors.tabs_in(None) == []


# ── target forms ──


def test_a_target_form_reads_the_console_actor_wrapped_or_flat():
    wrapped = {"from": "d", "form": {"consoleActor": "consoleActor1", "actor": "target1"}}
    flat = {"from": "d", "consoleActor": "consoleActor1", "type": "tabAttached"}
    assert actors.console_actor_of(actors.target_form(wrapped)) == "consoleActor1"
    assert actors.console_actor_of(actors.target_form(flat)) == "consoleActor1", \
        "attach answers flat — the same reader handles both"
    assert actors.target_form(None) == {}
    assert actors.console_actor_of({"screenshotActor": "s"}) == ""


def test_actor_types_reads_both_spellings_the_server_uses():
    assert actors.actor_types({"types": ["evaluateJS", "substring"]}) == {"evaluateJS", "substring"}
    assert actors.actor_types({"requestTypes": ["evaluateJSAsync"]}) == {"evaluateJSAsync"}
    assert actors.actor_types({"types": "nope"}) == set()
    assert actors.actor_types(None) == set()


def test_require_actor_refuses_an_empty_console_actor_by_name():
    assert actors.require_actor("consoleActor1") == "consoleActor1"
    with pytest.raises(wire.RdpError) as exc:
        actors.require_actor("")
    assert "console actor" in str(exc.value)


# ── evaluation replies ──


def test_a_result_id_pairs_an_async_reply_with_its_event():
    reply = {"from": "consoleActor1", "resultID": "result-7"}
    event = {"from": "consoleActor1", "type": "evaluationResult", "resultID": "result-7"}
    other = {"from": "consoleActor1", "type": "evaluationResult", "resultID": "result-8"}
    assert actors.result_id(reply) == "result-7"
    assert actors.result_id(None) == ""
    assert actors.result_matches(event, "result-7") is True
    assert actors.result_matches(other, "result-7") is False
    assert actors.result_matches(event, "") is False
    assert actors.result_matches(None, "result-7") is False


def test_grips_are_read_by_type_and_never_coerced():
    number = {"result": {"type": "number", "value": 2}}
    text = {"result": {"type": "string", "value": "Arena"}}
    assert actors.string_value(text) == "Arena"
    assert actors.string_value(number) is None, "a number is not silently stringified"
    assert actors.result_grip(number) == {"type": "number", "value": 2}
    assert actors.result_grip({"result": "junk"}) == {}
    assert actors.result_grip(None) == {}


def test_a_long_string_grip_reports_its_head_its_length_and_its_actor():
    grip = {"result": {"type": "longString", "actor": "longString1",
                       "length": 88, "initial": "Z" * 32}}
    assert actors.is_long_string(grip) is True
    assert actors.initial_text(grip) == "Z" * 32
    assert actors.total_length(grip) == 88
    assert actors.total_length({"result": {"type": "longString", "length": "many"}}) == 0
    assert actors.is_long_string({"result": {"type": "string", "value": "short"}}) is False
    assert actors.substring_text({"substring": "Z" * 88}) == "Z" * 88
    assert actors.substring_text(None) == ""


def test_an_exception_reply_reports_the_pages_own_text():
    failed = {"exceptionMessage": "Error: boom", "exception": {"type": "object"}}
    assert actors.exception_text(failed) == "Error: boom"
    assert actors.exception_text({"exception": {"type": "object"}}) == "JS exception"
    assert actors.exception_text({"result": {"type": "number", "value": 1}}) == ""
    assert actors.exception_text(None) == ""


# ── events vs replies vs errors ──


def test_a_typed_console_push_is_an_event_while_a_typed_reply_is_not():
    assert actors.is_event({"from": "server1.conn1.consoleActor1", "type": "pageError"}) is True
    assert actors.is_event({"from": "x", "type": "evaluationResult"}) is True
    assert actors.is_event({"from": "server1.conn1.tabDescriptor1", "type": "tabAttached"}) is False, \
        "tabAttached answers attach — treating it as an event would lose the reply"
    assert actors.is_event({"from": "server1.conn1.consoleActor1", "resultID": "r"}) is False
    assert actors.is_event({}) is False


def test_a_failed_request_carries_the_servers_own_error_name():
    error = actors.packet_error({"from": "a", "error": "noSuchActor", "message": "no such actor a"})
    assert error.startswith("noSuchActor")
    assert actors.packet_error({"from": "a"}) == ""
    assert actors.packet_error(None) == ""


# ── the click-only expression ──


def test_the_click_expression_is_one_statement_clicks_once_and_escapes_the_selector():
    expression = actors.click_expression("#go")
    assert expression.count(".click()") == 1, "one click, not one per branch"
    assert 'document.querySelector("#go")' in expression
    assert "JSON.stringify({ok:true" in expression and "JSON.stringify({ok:false" in expression
    hostile = actors.click_expression('a[href="x"]')
    assert 'document.querySelector("a[href=\\"x\\"]")' in hostile
    empty = actors.click_expression("")
    assert 'document.querySelector("")' in empty, "an empty selector is the page's problem, not a crash"


def test_a_click_verdict_is_only_read_from_a_json_object():
    ok = {"result": {"type": "string", "value": '{"ok": true, "why": "clicked"}'}}
    assert actors.click_verdict(ok) == {"ok": True, "why": "clicked"}
    assert actors.click_verdict({"result": {"type": "string", "value": "not json"}}) == {}
    assert actors.click_verdict({"result": {"type": "number", "value": 1}}) == {}
    assert actors.click_verdict({"result": {"type": "string", "value": '["ok"]'}}) == {}
    assert actors.click_verdict({}) == {}


# ── handle rules (the leaf module the panel asks) ──


def test_an_rdp_handle_is_refused_by_name_and_a_tab_socket_is_not():
    refusal = protocols.connect_refusal("rdp://127.0.0.1:6000/ctx-3")
    assert "DevTools" in refusal and "one socket" in refusal.lower()
    assert protocols.connect_refusal("ws://127.0.0.1:9222/devtools/page/AAA111") == ""
    assert protocols.refuses_tab_socket("rdp://h/ctx-1") is True
    assert protocols.refuses_tab_socket("ws://h/devtools/page/x") is False


def test_the_port_in_a_handle_is_read_when_it_is_there():
    assert protocols.port_in("ws://127.0.0.1:9224/devtools/page/x") == 9224
    assert protocols.port_in("ws://localhost/devtools/page/x") == 0
    assert protocols.port_in("") == 0
    assert protocols.port_in(None) == 0


def test_the_protocol_names_are_the_ones_the_registry_uses():
    from app.browser import browsers
    assert browsers.PROTOCOL_CDP == protocols.PROTOCOL_CDP
    assert browsers.PROTOCOL_RDP == protocols.PROTOCOL_RDP
    assert browsers.PROTOCOL_BIDI == protocols.PROTOCOL_BIDI
    assert protocols.DEFAULT_DEBUGGER_PORT == 6000, "Firefox's DevTools server default"
