"""RDP client — tabs, evaluate, click-only actions (2026-09-21, round 8).

The acceptance that makes this channel usable: **the tab identity survives a
reconnect**. Firefox's actor ids are per connection (`server1.connN.…`), so a
client that remembers an actor is broken by design — the tab's
`browsingContextID` is the identity, and every actor is resolved per operation.

The second acceptance is honesty: an expired actor is re-resolved once (not in a
loop), a protocol that cannot do an operation says so by name, and a dead socket
returns `(None, reason)` — never raises into the caller's UI path.

RED at `464185a`: `app.browser.rdp` did not exist.
"""

import json

import pytest

from app.browser.rdp import actors, wire
from app.browser.rdp.actors import click_expression
from app.browser import rdp
from tests.fakes.rdp_stub_server import RdpStubServer

pytestmark = pytest.mark.unit

ENDPOINT_PORT = "9229"


def _point(port: int) -> "wire.Endpoint":
    return wire.Endpoint("127.0.0.1", port)


@pytest.fixture
def stub():
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()


# ── identity + listing ──


def test_list_targets_names_tabs_by_browsing_context_not_by_actor(stub):
    targets, err = rdp.list_targets(_point(stub.port))
    assert err == ""
    assert [t.id for t in targets] == ["ctx-3", "ctx-4"]
    assert targets[0].title == "Arena" and targets[0].url == "https://arena.ai/c/1"
    assert targets[1].title == "Проверка 🚀", "non-ASCII titles survive the wire"
    assert all(t.protocol == "rdp" for t in targets)
    assert targets[0].ws_url == f"rdp://127.0.0.1:{stub.port}/ctx-3", "a handle, not a socket"


def test_the_tab_identity_survives_a_reconnect(stub):
    """Re-pointed in round 11: `ctx-N` is stable, and the two listings share one socket.

    The old pin asserted `stub.connections == 2` — a fresh socket per call. That is what
    made Firefox ask for permission on every listing (see `tests/test_rdp_session.py`),
    so the identity is now proven across an explicit reconnect instead of a silent one.
    """
    from app.browser.rdp import session as sess
    first, _ = rdp.list_targets(_point(stub.port))
    second, _ = rdp.list_targets(_point(stub.port))
    assert [t.id for t in first] == [t.id for t in second], "ctx ids are stable (R2)"
    assert stub.connections == 1, "and the second listing reused the socket"
    sess.close_all()                       # an explicit reconnect, as a restart would be
    third, _ = rdp.list_targets(_point(stub.port))
    assert [t.id for t in third] == [t.id for t in first], "the identity outlives the socket"
    assert stub.connections == 2
    assert [t.actor for t in third] != [t.actor for t in first], "while the actors do not"


def test_a_dead_socket_returns_a_reason_and_never_raises():
    port = 1  # nothing listens here
    targets, err = rdp.list_targets(_point(port), timeout=0.4)
    assert targets == [] and err
    value, err = rdp.evaluate_json(_point(port), "ctx-3", "1+1", timeout=0.4)
    assert value is None and err
    ok, err = rdp.click(_point(port), "ctx-3", "#send", timeout=0.4)
    assert ok is False and err


# ── evaluate ──


def test_evaluate_returns_the_value_over_the_async_result_id(stub):
    value, err = rdp.evaluate_json(_point(stub.port), "ctx-3", "JSON.stringify(document.title)")
    assert err == ""
    assert value == "Arena"
    assert stub.was_sent("evaluateJSAsync") and stub.was_sent("getTarget")


def test_evaluate_reads_a_long_string_through_substring():
    server = RdpStubServer()
    try:
        value, err = rdp.evaluate_json(_point(server.port), "ctx-3", "document.title + 'longString'")
        assert err == "", err
        assert value == "Z" * 80, "the whole long string, not the grip's 32-character head"
        assert server.was_sent("substring")
    finally:
        server.close()


def test_evaluate_falls_back_to_the_legacy_command_when_the_server_lacks_the_async_one():
    server = RdpStubServer(async_eval=False)
    try:
        value, err = rdp.evaluate_json(_point(server.port), "ctx-3", "JSON.stringify(document.title)")
        assert (value, err) == ("Arena", "")
        assert server.was_sent("requestTypes") and not server.was_sent("evaluateJSAsync")
        assert server.was_sent("evaluateJS")
    finally:
        server.close()


def test_evaluate_prefers_attach_when_gettarget_hides_the_console_actor():
    server = RdpStubServer(legacy_attach=True)
    try:
        value, err = rdp.evaluate_json(_point(server.port), "ctx-3", "JSON.stringify(document.title)")
        assert (value, err) == ("Arena", "")
        assert server.was_sent("attach")
    finally:
        server.close()


def test_evaluate_reports_a_js_exception_without_raising(stub):
    value, err = rdp.evaluate_json(_point(stub.port), "ctx-3", "boom()")
    assert value is None
    assert "boom" in err, "the page's own error text reaches the caller"


def test_an_unknown_tab_id_is_refused_by_name(stub):
    value, err = rdp.evaluate_json(_point(stub.port), "ctx-99", "1+1")
    assert value is None and "ctx-99" in err


# ── actor expiry (the real Firefox behaviour) ──


def test_each_attach_resolves_its_own_actors_and_caches_no_ids(stub):
    first, _ = rdp.evaluate_json(_point(stub.port), "ctx-3", "1+1")
    assert first == 2
    second, err = rdp.evaluate_json(_point(stub.port), "ctx-3", "1+1")   # actor died with the socket
    assert (second, err) == (2, ""), "a fresh connection resolves fresh actors — no cached actor ids"


def test_a_stale_actor_is_resolved_again_and_the_call_still_succeeds():
    """The real Firefox case: the actor is renamed under us on navigation."""
    server = RdpStubServer(stale_evals=1)
    try:
        value, err = rdp.evaluate_json(_point(server.port), "ctx-3", "JSON.stringify(document.title)")
        assert (value, err) == ("Arena", ""), "one re-resolve, one retry"
        assert server.was_sent("getTarget"), "and the actor was looked up again"
    finally:
        server.close()


def test_a_reconnecting_client_keeps_working_while_the_firefox_session_never_restarts():
    """Round 11 re-point: three operations, **one** socket — a new one per call asks Firefox again."""
    server = RdpStubServer()
    try:
        for _ in range(3):
            value, err = rdp.evaluate_json(_point(server.port), "ctx-3", "JSON.stringify(document.title)")
            assert (value, err) == ("Arena", "")
        assert server.connections == 1, "three evaluations, one browser session, one socket"
    finally:
        server.close()


def test_an_actor_that_never_comes_back_is_named_after_one_retry():
    server = RdpStubServer(expire_hard=True)
    try:
        value, err = rdp.evaluate_json(_point(server.port), "ctx-3", "1+1")
        assert value is None and "noSuchActor" in err
        evals = [p for p in server.received if p.get("type") == "evaluateJSAsync"]
        assert len(evals) <= 3, "one retry after one re-resolve, never a retry loop"
    finally:
        server.close()


# ── click-only actions ──


def test_the_click_expression_is_click_only_js():
    expression = click_expression("#send")
    assert "#send" in expression
    assert ".click()" in expression, "a click-only action is a JS click, not a synthesized input"
    assert "dispatchEvent" not in expression and "MouseEvent" not in expression, \
        "synthesized events add a fingerprint without becoming trusted — el.click() is the honest primitive"
    assert "JSON.stringify" in expression, "the caller gets a JSON verdict back"


def test_click_reports_success_and_failure_as_json(stub):
    ok, err = rdp.click(_point(stub.port), "ctx-3", "#send")
    assert (ok, err) == (True, "")
    sent = [p for p in stub.received if p.get("type") == "evaluateJSAsync"][-1]
    assert ".click()" in sent["text"]


def test_a_click_on_a_missing_element_reports_the_reason():
    server = RdpStubServer(click_found=False)
    try:
        ok, err = rdp.click(_point(server.port), "ctx-3", "#gone")
        assert (ok, err) == (False, "not found"), "not-there is an answer, not an exception"
    finally:
        server.close()


def test_the_verdict_parser_ignores_a_reply_that_is_not_a_verdict():
    assert actors.click_verdict({"result": {"type": "string", "value": "nope"}}) == {}
    assert actors.click_verdict({"result": {"type": "number", "value": 1}}) == {}


def test_click_escapes_a_hostile_selector():
    expression = click_expression('a[href="x"] onmouseover=alert(1)')
    assert "onmouseover=alert(1)" in expression
    assert expression.count('"') % 2 == 0, "the selector is embedded as JSON, quotes included"


def test_session_info_reports_protocol_facts_not_guesses(stub):
    info, err = rdp.session_info(_point(stub.port))
    assert err == ""
    assert info["application"] == "browser"
    assert info["prefix"].startswith("server1.conn")
    assert info["tabs"] == 2
    assert info["protocol"] == "rdp"
