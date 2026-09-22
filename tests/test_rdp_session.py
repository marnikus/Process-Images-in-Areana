"""One socket per Firefox, one dialog, and then nothing (round 11).

The owner: "App sends never-ending permission request messages … Popup keeps reappearing —
user must click Allow repeatedly. remove it completely. should stop sending it".

Measured at `40c13e5`, one listing pass opened **fifteen** DevTools sockets (3 listings,
2 pool joins, 10 evaluates) and Firefox asks about every incoming connection
(`devtools/shared/security/auth.js:169` reads `devtools.debugger.prompt-connection` per
connection), so the dialog came back roughly every second and again on every pass.

These tests drive the real stub server — which now models the dialog (`prompt=True`:
a connection is greeted only after it is allowed, and every dialog is counted) and the
parent process (`listProcesses` → chrome console, the only actor allowed to touch
`Services.prefs`). They are RED at `40c13e5`: there is no session, so each call dials again.
"""

import threading

import pytest

from app.browser import endpoints
from app.browser.rdp import client as rdp_client
from app.browser.rdp import session as sess
from app.browser.rdp.wire import Endpoint
from tests.fakes.rdp_stub_server import PROMPT_PREF, SETPROMPT_JS, RdpStubServer

pytestmark = pytest.mark.unit


@pytest.fixture
def stub():
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()
        sess.close_all()


@pytest.fixture
def asking():
    """A Firefox whose `prompt-connection` is still true — it asks before it answers."""
    server = RdpStubServer(prompt=True, prompt_wait=5.0)
    try:
        yield server
    finally:
        server.close()
        sess.close_all()


@pytest.fixture(autouse=True)
def _short_wait(monkeypatch):
    """The real wait is 25 s (a human answering a dialog); tests cannot sit through it."""
    monkeypatch.setattr(sess, "ALLOW_WAIT", 0.35)
    monkeypatch.setattr(sess, "GREETING_WAIT", 0.15)


def _point(stub) -> Endpoint:
    return Endpoint("127.0.0.1", stub.port)


# ── D-1: one socket per endpoint, whatever the app does with it ──────────────

def test_one_socket_serves_every_operation_not_one_per_operation(stub):
    """Fifteen sockets per pass was fifteen chances to be asked for permission."""
    point = _point(stub)
    rdp_client.list_targets(point)
    rdp_client.session_info(point)
    rdp_client.list_targets(point)
    rdp_client.evaluate_json(point, "ctx-3", "document.title")
    rdp_client.click(point, "ctx-3", "#send")
    assert stub.connections == 1, f"one Firefox, one socket — got {stub.connections}"


def test_a_second_pass_reuses_the_socket_it_already_has(stub):
    """The reconciler passes forever; it must not ask Firefox to allow it every pass."""
    point = _point(stub)
    rows, err = rdp_client.list_targets(point)
    again, err2 = rdp_client.list_targets(point)
    assert err == err2 == "" and [r.id for r in rows] == [r.id for r in again] == ["ctx-3", "ctx-4"]
    assert stub.connections == 1


def test_a_dropped_socket_is_replaced_once_not_once_per_operation(stub):
    """After Firefox closes the socket, the next operation reconnects — and only it does."""
    point = _point(stub)
    rdp_client.list_targets(point)
    sess.close_all()
    rdp_client.list_targets(point)
    rdp_client.evaluate_json(point, "ctx-3", "1+1")
    assert stub.connections == 2, "one reconnect, then reuse"


# ── D-2: the dialog is waited for, not raced ─────────────────────────────────

def test_the_first_attach_waits_for_the_dialog_and_then_lists(asking):
    """Firefox asks; the user clicks Allow; the socket was open all along — so it just works."""
    threading.Timer(0.1, asking.allow_pending).start()
    rows, err = rdp_client.list_targets(_point(asking))
    assert err == "" and [r.id for r in rows] == ["ctx-3", "ctx-4"]
    assert asking.prompts == 1, "the dialog is shown once, not once per attempt"


def test_the_wait_is_announced_before_it_happens(asking, caplog):
    """A silent 25 s would look like a hang; the log says what is on screen."""
    threading.Timer(1.5, asking.allow_pending).start()
    with caplog.at_level("INFO"):
        rdp_client.list_targets(_point(asking))
    assert any("Allow" in rec.message for rec in caplog.records), caplog.text


def test_a_dialog_nobody_answers_parks_and_stops_asking(asking):
    """"should stop sending it": one named reason, and then nothing at all.

    The first encounter costs one extra connection — the HTTP identity question that
    keeps a BiDi Firefox from being mistaken for a dialog (see `session.http_identity`),
    and every connection to a prompting server is a dialog. After that the endpoint is
    parked and **no pass opens anything**, which is the owner's complaint.
    """
    rows, err = rdp_client.list_targets(_point(asking))
    assert rows == [] and "Allow" in err
    touched = (asking.connections, asking.prompts)
    assert touched[0] <= 2, f"bounded: {touched}"
    again, err2 = rdp_client.list_targets(_point(asking))
    assert again == [] and err2 == err, "the same reason, not a new dialog"
    assert (asking.connections, asking.prompts) == touched, "an auto pass must not ask again"


def test_an_explicit_retry_is_allowed_to_ask_once_more(asking):
    """Reparse / Refresh / Diagnose are the user saying "try again", so they may."""
    rdp_client.list_targets(_point(asking))
    before = asking.connections
    sess.retry_all()
    rows, err = rdp_client.list_targets(_point(asking))
    assert rows == [] and "Allow" in err
    assert asking.connections > before, "the retry really did dial again"
    after = asking.connections
    rdp_client.list_targets(_point(asking))
    assert asking.connections == after, "and then it is parked again"


def test_the_reconciler_skips_a_parked_browser_without_opening_a_socket(asking, monkeypatch):
    """The scan seam is where the park has to hold, or every pass dials again."""
    rows = {"chrome": {"enabled": False}, "firefox": {"enabled": True, "port": asking.port},
            "edge": {"enabled": False}}
    targets, notes = endpoints.enabled_targets(rows, 9230, "127.0.0.1", 1.0)
    assert targets == [] and len(notes) == 1 and "Allow" in notes[0].reason
    touched = (asking.connections, asking.prompts)
    endpoints.enabled_targets(rows, 9230, "127.0.0.1", 1.0)
    endpoints.enabled_targets(rows, 9230, "127.0.0.1", 1.0)
    assert (asking.connections, asking.prompts) == touched, "no pass may dial a parked browser"


# ── D-3: the running Firefox is told to stop asking, for good ────────────────

def test_the_first_allowed_attach_suppresses_the_pref_in_the_running_browser(asking):
    """The dialog is answered once; the app then asks Firefox to stop showing it."""
    asking.allow_pending()
    rdp_client.list_targets(_point(asking))
    assert asking.prefs[PROMPT_PREF] is False, "the running profile must be told"
    assert asking.pref_writes, "the write went through the chrome console"


def test_after_suppression_a_reconnect_is_never_asked_again(asking):
    """This is "remove it completely": one Allow, then no dialog — now or next run."""
    threading.Timer(0.1, asking.allow_pending).start()
    rdp_client.list_targets(_point(asking))
    sess.retry_all()
    rows, err = rdp_client.list_targets(_point(asking))
    assert err == "" and [r.id for r in rows] == ["ctx-3", "ctx-4"]
    assert asking.connections == 2, "it really did reconnect"
    assert asking.prompts == 1, "and it was not asked a second time"


def test_a_tab_console_cannot_touch_prefs_only_the_chrome_process_can(stub):
    """The whole route only works in Firefox's own scope — so it must be asked there."""
    with rdp_client.attach(_point(stub)) as client:          # a raw socket, no session
        reply = client.evaluate("ctx-3", SETPROMPT_JS)
        value, err = client.value_of(reply, 2.0)
    assert err == "" and value.get("ok") is False, value
    assert stub.prefs[PROMPT_PREF] is True, "a page console must never be able to do this"
    assert stub.pref_writes == [], "and nothing may be recorded as written"


def test_a_firefox_without_a_chrome_process_degrades_with_a_reason():
    """Older/hardened builds may refuse the parent process: say so, keep the session."""
    server = RdpStubServer(no_chrome=True)
    try:
        ok, reason = rdp_client.suppress_prompt(_point(server), 2.0)
        assert ok is False and "Allow" in reason, reason
        rows, err = rdp_client.list_targets(_point(server))
        assert err == "" and rows, "the channel still works without the suppression"
    finally:
        server.close()
        sess.close_all()


def test_the_pref_is_written_through_the_chrome_console(stub):
    """And the write really happens in chrome scope (the stub records it there only)."""
    ok, reason = rdp_client.suppress_prompt(_point(stub), 2.0)
    assert ok is True and "prompt-connection=false" in reason
    assert stub.prefs[PROMPT_PREF] is False and stub.pref_writes


class _FakeClient:
    """Just enough client for the suppression contract (no socket involved)."""

    def __init__(self, reply=None, boom=None):
        self.reply, self.boom = reply or {}, boom
        self.expressions = []

    def chrome_eval(self, expression, timeout=None):
        self.expressions.append(expression)
        if self.boom is not None:
            raise self.boom
        return self.reply

    def value_of(self, reply, timeout=None):
        return reply.get("value"), reply.get("error", "")


def test_a_broken_actor_tree_is_reported_not_raised():
    """A prefs write must never take the pass down with it."""
    from app.browser.rdp import prefs
    ok, reason = prefs.ask_to_stop(_FakeClient(boom=RuntimeError("actor gone")), 1.0)
    assert ok is False and "actor gone" in reason and "Allow" in reason


def test_a_reply_that_is_not_the_expected_value_is_not_a_success():
    """Trust the browser's answer, not the fact that we sent something."""
    from app.browser.rdp import prefs
    ok, reason = prefs.ask_to_stop(_FakeClient(reply={"error": "ReferenceError: Services"}), 1.0)
    assert ok is False and "Services" in reason
    ok, reason = prefs.ask_to_stop(_FakeClient(reply={"value": "false"}), 1.0)
    assert ok is False and "Allow" in reason


def test_the_conversion_expression_is_the_pref_we_mean():
    """One line to audit: the pref, its value, and no other change."""
    from app.browser.rdp import prefs
    client = _FakeClient(reply={"value": f"{prefs.PROMPT_PREF}=false"})
    ok, reason = prefs.ask_to_stop(client, 1.0)
    assert ok is True and "prompt-connection=false" in reason
    assert client.expressions == [prefs.SUPPRESS_JS]
    assert prefs.PROMPT_PREF in prefs.SUPPRESS_JS and "setBoolPref" in prefs.SUPPRESS_JS


def test_the_panel_can_print_what_happened_to_the_dialog(stub):
    """The outcome is one line the user can read, and it is drained (never repeated)."""
    sess.drain_news()                    # never inherit another test's lines
    rdp_client.list_targets(_point(stub))
    news = sess.drain_news()
    assert len(news) == 1 and "prompt-connection" in news[0], news
    assert sess.drain_news() == [], "one line per endpoint, not one per pass"


def test_suppression_is_attempted_once_per_endpoint(stub):
    """A worked pref must not be re-sent on every listing (one line per endpoint)."""
    point = _point(stub)
    rdp_client.list_targets(point)
    rdp_client.list_targets(point)
    rdp_client.evaluate_json(point, "ctx-3", "1+1")
    assert len(stub.pref_writes) == 1, stub.pref_writes
