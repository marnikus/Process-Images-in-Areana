"""B8 — the shared click runner survives a transient page-context loss.

Before: one empty FIND answer → "no data returned from the page (page
context unavailable?)" → block failed, even when the page was back a second
later. Now the runner reports the transport's real reason, waits for the
document (reconnecting a closed socket) and re-probes; non-transient empties
(the probe threw) still fail on the first answer.

RULE 8: real `visual_click` + `page_recovery`; only the CDP client is faked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.browser import page_recovery as pr
from app.browser import visual_click as vc

pytestmark = pytest.mark.unit

FOUND = json.dumps({"found": True, "visible": True, "total": 1, "index": 0,
                    "rect": {"x": 1, "y": 1, "width": 5, "height": 5}})
STAGED = json.dumps({"clickable": True, "target_desc": "button#go"})
CLICKED = json.dumps({"clicked": True})


class ScriptedCDP:
    """Answers in order; None answers carry the transport's failure record."""

    def __init__(self, answers, kind="protocol", error="Execution context was destroyed.",
                 connected=True):
        self.answers = list(answers)
        self.last_error = ""
        self.last_error_kind = ""
        self._kind, self._error = kind, error
        self.is_connected = connected
        self._current_ws_url = "ws://127.0.0.1:9222/devtools/page/T1"
        self.connect_calls = []
        self.calls = []

    async def evaluate(self, js):
        self.calls.append(js)
        value = self.answers.pop(0) if self.answers else None
        if value is None:
            self.last_error, self.last_error_kind = self._error, self._kind
        else:
            self.last_error = self.last_error_kind = ""
        return value

    async def connect(self, url):
        self.connect_calls.append(url)
        self.is_connected = True
        return True


class Engine:
    def __init__(self):
        self.lines = []

    def report(self, msg, level="info"):
        self.lines.append((msg, level))

    def text(self):
        return " | ".join(m for m, _ in self.lines)


def _instant(monkeypatch):
    async def _sleep(_s):
        return None
    monkeypatch.setattr(pr.asyncio, "sleep", _sleep)
    monkeypatch.setattr(vc.asyncio, "sleep", _sleep)


def _req(**kw):
    kw.setdefault("selector", "button#go")
    kw.setdefault("label", "Go button")
    kw.setdefault("confirm_pause_ms", 0)
    return vc.ClickRequest(**kw)


@pytest.mark.asyncio
async def test_find_recovers_from_context_destroyed_and_retries(monkeypatch):
    _instant(monkeypatch)
    # probe → empty (context destroyed); readiness → complete; probe → found
    cdp = ScriptedCDP(answers=[None, "complete", FOUND])
    eng = Engine()
    res = await vc.find_phase(cdp, _req(), engine=eng)
    assert res is not None and res["found"] is True
    assert len(cdp.calls) == 3 and cdp.calls[1] == pr._READY_JS
    text = eng.text()
    assert "Execution context was destroyed" in text and "page context is back" in text
    assert "❌ FIND failed" not in text


@pytest.mark.asyncio
async def test_find_reports_real_reason_when_page_never_returns(monkeypatch):
    _instant(monkeypatch)
    cdp = ScriptedCDP(answers=[])  # every answer empty: probe, then 3 readiness rounds
    eng = Engine()
    assert await vc.find_phase(cdp, _req(), engine=eng) is None
    fails = [m for m, lvl in eng.lines if m.startswith("❌ FIND failed")]
    assert fails and "Execution context was destroyed" in fails[-1]
    assert "page context unavailable?" not in fails[-1]  # the guess is gone when we know
    probes = [c for c in cdp.calls if c != pr._READY_JS]
    readiness = [c for c in cdp.calls if c == pr._READY_JS]
    # recovery exhausted → no point re-probing; the page never answered
    assert (len(probes), len(readiness)) == (1, pr.RECOVERY_ATTEMPTS)


@pytest.mark.asyncio
async def test_find_does_not_retry_when_the_probe_threw(monkeypatch):
    _instant(monkeypatch)
    cdp = ScriptedCDP(answers=[None, FOUND], kind="js", error="TypeError: boom at probe")
    eng = Engine()
    assert await vc.find_phase(cdp, _req(), engine=eng) is None
    assert len(cdp.calls) == 1  # a real JS answer: fail fast, never re-probe
    assert "TypeError: boom at probe" in eng.text()


@pytest.mark.asyncio
async def test_find_reconnects_closed_socket_then_succeeds(monkeypatch):
    _instant(monkeypatch)
    cdp = ScriptedCDP(answers=[None, "complete", FOUND], kind="transport",
                      error="ConnectionClosedOK: received 1000 (OK)", connected=False)
    eng = Engine()
    res = await vc.find_phase(cdp, _req(), engine=eng)
    assert res is not None and res["found"] is True
    assert cdp.connect_calls == ["ws://127.0.0.1:9222/devtools/page/T1"]
    assert "reconnecting to the same tab" in eng.text()


@pytest.mark.asyncio
async def test_legacy_fake_without_contract_fails_once_with_old_wording():
    async def _none(_js):
        return None
    calls = []

    async def evaluate(js):
        calls.append(js)
        return await _none(js)
    cdp = SimpleNamespace(evaluate=evaluate)
    eng = Engine()
    assert await vc.find_phase(cdp, _req(), engine=eng) is None
    assert len(calls) == 1
    assert "no data returned from the page (page context unavailable?)" in eng.text()


@pytest.mark.asyncio
async def test_run_click_recovers_in_stage_but_never_retries_the_click(monkeypatch):
    _instant(monkeypatch)
    # find ok → stage empty (transient) → ready → stage ok → click empty (transient)
    cdp = ScriptedCDP(answers=[FOUND, None, "complete", STAGED, None])
    eng = Engine()
    assert await vc.run_click(cdp, _req(), engine=eng) == "fail"
    probes = [c for c in cdp.calls if c != pr._READY_JS]
    assert len(probes) == 4  # find, stage, stage-again, click — click dispatched exactly once
    text = eng.text()
    assert "no data returned from the click (Execution context was destroyed.)" in text


@pytest.mark.asyncio
async def test_run_click_happy_path_after_recovery(monkeypatch):
    _instant(monkeypatch)
    cdp = ScriptedCDP(answers=[None, "complete", FOUND, STAGED, CLICKED])
    eng = Engine()
    assert await vc.run_click(cdp, _req(), engine=eng) == "ok"
