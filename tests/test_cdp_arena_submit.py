"""CDPArenaController.submit_when_ready — Send-ready poll for resubmits.

RULE 8: the real controller methods against a scripted fake CDP (state
probe answers canned, click probe records). Small timeouts keep the
0.5 s poll sleeps cheap. The JS probes' DOM behaviour is covered by
tests/js/test_composer_probes.mjs against the real const strings.
"""

import pytest

from app.browser.cdp_arena import CDPArenaController
from app.browser.composer_probes import build_insert_prompt_js

ENABLED = {"found": True, "visible": True, "enabled": True}
DISABLED = {"found": True, "visible": True, "enabled": False}
HIDDEN = {"found": True, "visible": False, "enabled": False}
MISSING = {"found": False, "visible": False, "enabled": False}


class FakeCdp:
    """Scripted CDP: canned send-states, records clicks."""

    def __init__(self, states, connected=True, corpus=""):
        self.is_connected = connected
        self._states = list(states)
        self.clicks = 0
        self.state_polls = 0
        self._corpus = corpus

    async def evaluate(self, js):
        if 'role="alert"' in js:  # error-scan probe
            return self._corpus
        if "if(!els.length)" in js:  # JS_SEND_STATE probe
            self.state_polls += 1
            if len(self._states) > 1:
                return self._states.pop(0)
            return self._states[0]
        if "btn.click()" in js:  # JS_CLICK_SEND probe
            self.clicks += 1
            return {"ok": True, "sel": "x"}
        return None  # highlight probes: fall through to the default rect


def ctrl_for(states, connected=True):
    return CDPArenaController(FakeCdp(states, connected))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clicks_immediately_when_enabled():
    ctrl = ctrl_for([ENABLED])
    assert await ctrl.submit_when_ready(timeout_sec=5) == (True, "Clicked")
    assert ctrl.cdp.clicks == 1 and ctrl.cdp.state_polls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_waits_for_react_to_enable_send():
    ctrl = ctrl_for([DISABLED, DISABLED, ENABLED])
    assert await ctrl.submit_when_ready(timeout_sec=5) == (True, "Clicked")
    assert ctrl.cdp.clicks == 1 and ctrl.cdp.state_polls == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terminal_state_when_never_enabled():
    ctrl = ctrl_for([DISABLED])
    assert await ctrl.submit_when_ready(timeout_sec=0.05) == (False, "send disabled")
    assert ctrl.cdp.clicks == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terminal_state_when_missing_or_hidden():
    assert await ctrl_for([MISSING]).submit_when_ready(timeout_sec=0.05) == (False, "send not found")
    assert await ctrl_for([HIDDEN]).submit_when_ready(timeout_sec=0.05) == (False, "send hidden")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_not_connected_short_circuits():
    ctrl = ctrl_for([ENABLED], connected=False)
    assert await ctrl.submit_when_ready(timeout_sec=5) == (False, "Not connected")
    assert ctrl.cdp.state_polls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scan_page_errors_returns_corpus():
    ctrl = CDPArenaController(FakeCdp([ENABLED], corpus="Something went wrong. Trace ID: 9"))
    assert await ctrl.scan_page_errors() == "Something went wrong. Trace ID: 9"
    assert await ctrl_for([ENABLED]).scan_page_errors() == ""


@pytest.mark.unit
def test_insert_probe_targets_visible_composer():
    # DOM behavior is exercised in tests/js/test_composer_prompt.mjs.
    probe = build_insert_prompt_js("hello")
    assert "visible prompt composer" in probe
    assert "_valueTracker" in probe
