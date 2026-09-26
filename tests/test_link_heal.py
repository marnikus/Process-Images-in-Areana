"""A closed DevTools socket is re-attached to the same tab, everywhere a job needs it (2026-09-26).

Field case (docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md
§1): a 20 MB image pulled through one evaluate reply closed the socket with
1009 and nothing reconnected — the save, the New-chat reset and every later
job failed on "CDP not connected".

RULE 8: the real `page_recovery`, output poll, New-chat reset and supervisor
functions; only the CDP client and the visual click are fakes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.browser import new_chat as nc
from app.browser import output_wait as ow
from app.browser import page_recovery as pr
from app.services.live import supervisor as sup
from app.services.live.bus import LiveBus

pytestmark = pytest.mark.unit


class Link:
    """The transport contract the healer reads: is_connected, ws url, connect, evaluate."""

    def __init__(self, connected=False, url="ws://127.0.0.1:9222/devtools/page/T1", comes_back=True):
        self.is_connected, self._current_ws_url, self.comes_back = connected, url, comes_back
        self.connects, self.last_error, self.last_error_kind = [], "", ""

    async def connect(self, url):
        self.connects.append(url)
        self.is_connected = self.comes_back
        return self.comes_back

    async def evaluate(self, js, await_promise=True):
        if not self.is_connected:
            self.last_error, self.last_error_kind = "CDP not connected", "transport"
            return None
        return "complete"


@pytest.fixture(autouse=True)
def instant(monkeypatch):
    async def _sleep(_s):
        return None
    monkeypatch.setattr(pr.asyncio, "sleep", _sleep)


async def test_heal_is_a_no_op_on_a_live_socket_and_on_fakes_without_the_contract():
    live = Link(connected=True)
    await pr.heal_link(live)
    await pr.heal_link(SimpleNamespace())
    assert live.connects == []


async def test_heal_reattaches_the_same_tab():
    link, said = Link(), []
    await pr.heal_link(link, lambda m, l="info": said.append(m))
    assert link.connects == [link._current_ws_url] and link.is_connected
    assert "🔌 reconnected" in said and "✅ page context is back — retrying" in said


async def test_heal_raises_link_lost_with_the_reason_when_the_tab_is_gone():
    link = Link(comes_back=False)
    with pytest.raises(pr.LinkLost, match=r"reconnect to the same tab failed \(CDP not connected\)"):
        await pr.heal_link(link)
    assert len(link.connects) == pr.RECOVERY_ATTEMPTS


@pytest.mark.parametrize("cdp,expected", [
    (None, False),
    (Link(connected=True), True),
    (Link(url=""), False),
    (SimpleNamespace(is_connected=False, _current_ws_url="ws://x"), False),   # no connect()
])
async def test_reconnect_same_tab_edges(cdp, expected):
    assert await pr.reconnect_same_tab(cdp) is expected


async def test_reconnect_that_raises_is_a_failed_reconnect():
    link = Link()

    async def boom(url):
        raise OSError("refused")
    link.connect = boom
    said = []
    assert await pr.reconnect_same_tab(link, lambda m, l="info": said.append((m, l))) is False
    assert said[-1] == ("🔌 reconnect failed", "warn")


async def test_the_output_poll_ends_at_once_on_a_lost_link():
    """LinkLost must not be swallowed as one more empty poll (the wait would burn its timeout)."""
    async def check():
        raise pr.LinkLost("CDP connection lost — reconnect to the same tab failed (x)")
    with pytest.raises(pr.LinkLost):
        await ow._poll_check(check, 0)
    diag, err = await ow._poll_check(_raises(ValueError("flaky")), 0)
    assert diag is None and err == {"ready": False, "reason": "flaky"}


def _raises(exc):
    async def check():
        raise exc
    return check


async def test_new_chat_reset_heals_first_and_names_a_lost_link(monkeypatch):
    clicks = []

    async def fake_click(client, req, engine=None):
        clicks.append(req.selector)
        return "ok"
    monkeypatch.setattr(nc, "find_and_click", fake_click)
    records = []
    engine = SimpleNamespace(report=lambda m, l="info": records.append((m, l)))
    ok, why = await nc.reset_to_new_chat(nc.ResetCtx(ctrl=None, client=Link(comes_back=False), engine=engine))
    assert ok is False and why.startswith("CDP connection lost") and clicks == []
    assert records[-1][1] == "error" and "New-chat reset failed: CDP connection lost" in records[-1][0]


def test_new_chat_clean_probe_also_counts_leftover_previews():
    js = nc.build_composer_empty_js()
    assert "previews === 0" in js and "__PREVIEW_SELECTORS__" not in js
    assert "div.flex.flex-wrap.gap-2 img[alt]" in js


async def test_supervisor_cdp_down_really_reconnects_throttled():
    logs = []
    link = Link()
    bridge = SimpleNamespace(cdp=link, _log=lambda m, l="info": logs.append(m))
    now = [0.0]
    bus = LiveBus(clock=lambda: now[0])
    assert await sup.heal_cdp(bridge, bus) is True and link.connects
    link.is_connected = False
    assert await sup.heal_cdp(bridge, bus) is False            # inside RECONNECT_MS: no retry storm
    now[0] += sup.RECONNECT_MS / 1000.0
    link.connect = _raising_connect
    bridge.cdp = SimpleNamespace(is_connected=False, _current_ws_url="ws://x", connect=_raising_connect)
    assert await sup.heal_cdp(bridge, bus) is False
    assert "🔌 reconnect failed" in logs


async def _raising_connect(url):
    raise OSError("refused")


async def test_supervisor_reports_an_unexpected_heal_error(monkeypatch):
    async def broken(cdp, report=None):
        raise RuntimeError("bug")
    monkeypatch.setattr(sup, "reconnect_same_tab", broken)
    logs = []
    bridge = SimpleNamespace(cdp=Link(), _log=lambda m, l="info": logs.append(m))
    assert await sup.heal_cdp(bridge, LiveBus(clock=lambda: 0.0)) is False
    assert logs == ["🔌 reconnect attempt failed: bug"]
