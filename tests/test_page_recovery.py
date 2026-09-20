"""B8 — transient page-context loss: classification + wait/reconnect loop.

Field case (bugfix-verification.md §B8): after the image was downloaded every
probe answered nothing for ~1 s (page mid-reload) and the block, the job and
the New-chat reset all failed on the first empty answer.

RULE 8: real `page_recovery` functions; only the CDP client is a fake that
replays the transport's `last_error` / `last_error_kind` contract.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.browser import page_recovery as pr

pytestmark = pytest.mark.unit


class FakeCDP:
    """Replays the transport contract: evaluate() answers from a script and
    the last_error fields describe every empty answer."""

    def __init__(self, answers, kind="protocol", error="Execution context was destroyed.",
                 connected=True, ws_url="ws://127.0.0.1:9222/devtools/page/T1"):
        self.answers = list(answers)
        self.last_error = ""
        self.last_error_kind = ""
        self._kind, self._error = kind, error
        self.is_connected = connected
        self._current_ws_url = ws_url
        self.connect_calls = []
        self.evaluated = []

    async def evaluate(self, js):
        self.evaluated.append(js)
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


def _instant(monkeypatch):
    async def _sleep(_s):
        return None
    monkeypatch.setattr(pr.asyncio, "sleep", _sleep)


# ── classification ──

@pytest.mark.parametrize("kind,error,expected", [
    ("protocol", "Execution context was destroyed.", True),
    ("protocol", "Cannot find default execution context", True),
    ("protocol", "Inspected target navigated or closed", True),
    ("protocol", "Object reference chain is too long", False),
    ("transport", "ConnectionClosedOK: received 1000 (OK)", True),
    ("transport", "ConnectionError: CDP not connected", True),
    ("transport", "TimeoutError: CDP command Runtime.evaluate timed out after 30s", False),
    ("js", "TypeError: boom", False),
    ("", "", False),
])
def test_is_transient_loss_classifies_transport_record(kind, error, expected):
    cdp = SimpleNamespace(last_error=error, last_error_kind=kind)
    assert pr.is_transient_loss(cdp) is expected


def test_fakes_without_the_contract_are_never_transient():
    assert pr.is_transient_loss(SimpleNamespace()) is False
    assert pr.evaluate_failure(SimpleNamespace()) == ""


# ── recovery loop ──

@pytest.mark.asyncio
async def test_recover_waits_until_document_answers(monkeypatch):
    _instant(monkeypatch)
    # the failed probe that triggers recovery, then: round 1 empty, round 2 loading, round 3 back
    cdp = FakeCDP(answers=[None, None, "loading", "complete"])
    assert await cdp.evaluate("probe") is None
    reports = []
    ok = await pr.recover_page_context(cdp, lambda m, lvl="info": reports.append((m, lvl)))
    assert ok is True
    assert len(cdp.evaluated) == 4 and cdp.evaluated[-1] == pr._READY_JS
    joined = " | ".join(m for m, _ in reports)
    assert "attempt 1/3" in joined and "attempt 3/3" in joined
    assert "Execution context was destroyed" in joined  # the real reason, not a guess
    assert "page context is back" in joined
    assert cdp.connect_calls == []  # socket was fine: never reconnects a live tab


@pytest.mark.asyncio
async def test_recover_gives_up_after_attempts(monkeypatch):
    _instant(monkeypatch)
    cdp = FakeCDP(answers=[])
    reports = []
    ok = await pr.recover_page_context(cdp, lambda m, lvl="info": reports.append((m, lvl)), attempts=2)
    assert ok is False
    assert len(cdp.evaluated) == 2
    assert reports[-1][1] == "error" and "did not come back after 2 attempts" in reports[-1][0]


@pytest.mark.asyncio
async def test_recover_reconnects_closed_socket_to_the_same_tab(monkeypatch):
    _instant(monkeypatch)
    cdp = FakeCDP(answers=["complete"], kind="transport",
                  error="ConnectionClosedOK: received 1000 (OK)", connected=False)
    reports = []
    ok = await pr.recover_page_context(cdp, lambda m, lvl="info": reports.append(m))
    assert ok is True
    assert cdp.connect_calls == ["ws://127.0.0.1:9222/devtools/page/T1"]
    assert any("reconnecting to the same tab" in m for m in reports)
    assert any(m == "🔌 reconnected" for m in reports)


@pytest.mark.asyncio
async def test_recover_reconnect_failure_is_reported_not_raised(monkeypatch):
    _instant(monkeypatch)

    class Dead(FakeCDP):
        async def connect(self, url):
            self.connect_calls.append(url)
            raise OSError("tab gone")

    cdp = Dead(answers=[], kind="transport", error="ConnectionError: CDP not connected",
               connected=False)
    reports = []
    ok = await pr.recover_page_context(cdp, lambda m, lvl="info": reports.append(m), attempts=1)
    assert ok is False
    assert cdp.connect_calls and "🔌 reconnect failed" in reports


@pytest.mark.asyncio
async def test_recover_without_reporter_and_without_ws_url(monkeypatch):
    _instant(monkeypatch)
    cdp = FakeCDP(answers=["interactive"], kind="transport", error="x", connected=False, ws_url="")
    assert await pr.recover_page_context(cdp) is True
    assert cdp.connect_calls == []  # nothing to reconnect to → just wait for the document
