"""A JavaScript dialog blocks every evaluate — notice it, answer it (I-71, 2026-09-27).

Owner log: after a manually solved captcha, `🔍 Output check: no_result`, the
image never saved and the New Chat reset hung at `FIND phase` — every
`Runtime.evaluate` on the tab timed out at 30 s. Measured in Chrome
(puppeteer-core, 2026-09-27): while `alert()` is open no evaluate is answered
on any connection, Chrome sends `Page.javascriptDialogOpening`, and
`Page.handleJavaScriptDialog` makes the page answer again at once.

The fake socket below behaves the way the measurement did (RULE 8: no live
Chrome): an evaluate sent while a dialog is open is held until the dialog is
answered; replies travel through the real `route_cdp_message`.
"""

import asyncio
import json

import pytest

from app.browser.cdp import dialogs as dl
from app.browser.cdp.transport import CDPTransport
from app.browser.cdp_events import route_cdp_message

pytestmark = pytest.mark.unit

ALERT = {"method": dl.DIALOG_OPENING,
         "params": {"type": "alert", "message": "Cannot contact reCAPTCHA. Check your connection and try again."}}


class DialogPage:
    """A page socket: evaluates answer 42 unless a dialog holds them."""

    def __init__(self, transport, dialog=None, fail_answer=False):
        self.t, self.dialog, self.fail_answer = transport, dialog, fail_answer
        self.held, self.methods = [], []

    async def send(self, payload):
        msg = json.loads(payload)
        self.methods.append(msg["method"])
        if msg["method"] == "Page.handleJavaScriptDialog":
            self._answer_dialog(msg)
        elif self.dialog:
            self.held.append(msg["id"])            # blocked behind the dialog
        else:
            self._reply(msg["id"], {"result": {"type": "number", "value": 42}})

    def open(self, event=ALERT):
        self.dialog = event
        route_cdp_message(self.t, event)           # Chrome tells every Page-enabled session

    def _answer_dialog(self, msg):
        if self.fail_answer:
            self._reply(msg["id"], None, error={"code": -32602, "message": "No dialog is showing"})
            return
        self.dialog = None
        self._reply(msg["id"], {})
        for held in self.held:                      # the page runs the queued evaluates now
            self._reply(held, {"result": {"type": "number", "value": 42}})
        self.held = []

    def _reply(self, cmd_id, result, error=None):
        data = {"id": cmd_id, "error": error} if error else {"id": cmd_id, "result": result}
        route_cdp_message(self.t, data)


def _transport(**page_kw):
    t = CDPTransport()
    t._connected = True
    page = DialogPage(t, **page_kw)
    t._ws = page
    notes = []
    t.dialogs.report = notes.append
    return t, page, notes


async def test_an_open_dialog_is_answered_before_the_evaluate_and_the_page_answers():
    t, page, notes = _transport()
    page.open()
    assert t.dialogs.open["type"] == "alert"
    assert await t.evaluate("1+1") == 42
    assert page.methods == ["Page.handleJavaScriptDialog", "Runtime.evaluate"]
    assert notes == ["💬 JavaScript alert 'Cannot contact reCAPTCHA. Check your connection and try "
                     "again.' was blocking the page — accepted, continuing"]
    assert t.last_error == ""


async def test_a_dialog_that_opens_while_the_evaluate_waits_is_answered_within_a_poll(monkeypatch):
    monkeypatch.setattr(dl, "DIALOG_POLL_S", 0.01)
    t, page, notes = _transport()
    page.dialog = ALERT                               # the page is blocked, the event is on its way
    job = asyncio.ensure_future(t.evaluate("document.title"))
    await asyncio.sleep(0.03)
    assert not job.done()                             # held behind the dialog
    route_cdp_message(t, ALERT)
    assert await asyncio.wait_for(job, timeout=1.0) == 42
    assert len(notes) == 1 and "accepted" in notes[0]


async def test_without_a_dialog_nothing_extra_is_sent():
    t, page, notes = _transport()
    assert await t.evaluate("1") == 42
    assert page.methods == ["Runtime.evaluate"] and notes == []


async def test_a_closed_event_forgets_the_dialog():
    t, page, notes = _transport()
    page.open()
    route_cdp_message(t, {"method": dl.DIALOG_CLOSED, "params": {"result": True}})
    page.dialog = None
    assert await t.evaluate("1") == 42
    assert page.methods == ["Runtime.evaluate"] and notes == []


async def test_a_failed_answer_is_told_once_and_never_retried_forever():
    t, page, notes = _transport(fail_answer=True)
    route_cdp_message(t, ALERT)                       # stale: Chrome has no dialog any more
    assert await t.evaluate("1") == 42
    assert await t.evaluate("2") == 42
    assert page.methods.count("Page.handleJavaScriptDialog") == 1
    assert len(notes) == 1 and "could not be closed" in notes[0]


@pytest.mark.parametrize("kind, accept", [("alert", True), ("beforeunload", True),
                                          ("confirm", False), ("prompt", False)])
def test_alerts_and_leave_prompts_are_accepted_questions_are_dismissed(kind, accept):
    assert dl.should_accept(kind) is accept


async def test_a_question_dialog_is_dismissed():
    t, page, notes = _transport()
    sent = []
    real_send = t.send

    async def spy(method, params=None, timeout=30):
        sent.append((method, params))
        return await real_send(method, params, timeout)
    t.send = spy
    page.open({"method": dl.DIALOG_OPENING, "params": {"type": "confirm", "message": "Delete?"}})
    assert await t.evaluate("1") == 42
    assert sent[0] == ("Page.handleJavaScriptDialog", {"accept": False})
    assert "dismissed" in notes[0]


def test_the_event_text_is_bounded_and_defaults_to_alert():
    assert dl.describe({"message": "x" * 500}) == {"type": "alert", "message": "x" * 200}


async def test_a_reporter_that_raises_falls_back_to_the_python_log():
    t, page, _notes = _transport()

    def broken(_msg):
        raise RuntimeError("ui gone")
    t.dialogs.report = broken
    page.open()
    assert await t.evaluate("1") == 42


async def test_a_cancelled_wait_cancels_its_command():
    t, page, _notes = _transport()
    page.dialog = ALERT                                # held forever, no event
    job = asyncio.ensure_future(dl.send_unblocked(t, "Runtime.evaluate", {"expression": "1"}))
    await asyncio.sleep(0.02)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    await asyncio.sleep(0)
    assert t._pending == {}                            # the inner send gave its slot back


# ── wiring: an answered dialog is a warn line in the UI log ────────────────

class LogBridge:
    def __init__(self):
        self.lines = []

    def _log(self, message, level="info"):
        self.lines.append((level, message))


def test_report_to_log_points_the_watch_at_the_ui_log():
    bridge, t = LogBridge(), CDPTransport()
    assert dl.report_to_log(t, bridge._log) is t
    t.dialogs.report("💬 note")
    assert bridge.lines == [("warn", "💬 note")]
    plain = object()
    assert dl.report_to_log(plain, bridge._log) is plain   # a client without a watch is left alone


def test_the_main_client_is_wired_by_wire_cdp():
    from types import SimpleNamespace
    from app.ui.bridge_context import wire_cdp
    bridge = LogBridge()
    bridge.cdp, bridge.connection_status = CDPTransport(), SimpleNamespace(emit=lambda *_: None)
    wire_cdp(bridge)
    bridge.cdp.dialogs.report("💬 main note")
    assert bridge.lines[-1] == ("warn", "💬 main note")


async def test_a_pool_client_reports_its_dialogs_to_the_ui_log(monkeypatch):
    import app.browser.cdp_client as cc
    from app.ui.panels import page_pool as pp

    class Client(CDPTransport):
        def __init__(self, host="127.0.0.1", port=9222):
            super().__init__(host, port)

        async def connect(self, _url):
            return True
    monkeypatch.setattr(cc, "CDPClient", Client)
    bridge = LogBridge()
    client = await pp.connect_pool_client(bridge, "ws://127.0.0.1:9222/devtools/page/2E0D3B")
    client.dialogs.report("💬 pool note")
    assert bridge.lines == [("warn", "💬 pool note")]
