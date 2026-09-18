"""Captcha completion (2026-09-18 captcha-completion).

The token was injected but the dialog never resumed: the dialog's
sitecallback is a JS closure an injected token never fires, and there is no
Continue button. Now: force-close completes the solve (token stays in the
field), the bridge flow re-sends the prompt once if the request died
(round-6 parity), and "Scan now" adds deep evidence (dialog markup,
grecaptcha surface, bundle source). Docs:
docs/archive/2026-09-18-captcha-completion/design.md
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.captcha.diagnose import deep_scan_lines
from app.ui.bridge import Bridge


def make_bridge(tmp_path) -> Bridge:
    cfg = ConfigManager(config_dir=str(tmp_path / "config"))
    return Bridge(cfg, tmp_path / "app_state.json")


@pytest.fixture
def instant_sleep(monkeypatch):
    async def instant(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


class FakeCtrl:
    def __init__(self, generating=False, has_prompt=True):
        self.generating = generating
        self.has_prompt = has_prompt
        self.submitted = []
        self.cdp = SimpleNamespace(evaluate=self._evaluate)

    async def _evaluate(self, js):
        return self.has_prompt

    async def is_generating(self):
        return self.generating, {}

    async def submit(self):
        self.submitted.append(1)
        return True, "Clicked"


@pytest.mark.unit
async def test_resubmit_skips_when_request_alive(tmp_path, instant_sleep):
    bridge = make_bridge(tmp_path)
    ctrl = FakeCtrl(generating=True, has_prompt=True)
    await bridge._post_genwait_resubmit(ctrl, "Q4DB")
    assert ctrl.submitted == []  # spinner = request alive, don't double-send


@pytest.mark.unit
async def test_resubmit_skips_when_no_prompt(tmp_path, instant_sleep):
    bridge = make_bridge(tmp_path)
    ctrl = FakeCtrl(generating=False, has_prompt=False)
    await bridge._post_genwait_resubmit(ctrl, "Q4DB")
    assert ctrl.submitted == []  # composer empty = nothing to send


@pytest.mark.unit
async def test_resubmit_resends_dead_request(tmp_path, instant_sleep):
    bridge = make_bridge(tmp_path)
    logs = []
    bridge._log = lambda m, l="info": logs.append((m, l))
    ctrl = FakeCtrl(generating=False, has_prompt=True)
    await bridge._post_genwait_resubmit(ctrl, "Q4DB")
    assert ctrl.submitted == [1]
    assert any("re-sent prompt" in m for m, _ in logs)
    assert any("[Q4DB]" in m for m, _ in logs)  # on the job's corr line


@pytest.mark.unit
def test_deep_scan_lines_with_evidence():
    deep = {
        "dialog_html": "<div role=dialog data-state=open>…</div>",
        "grecaptcha": {"keys": ["render", "getResponse"], "has_getResponse": True, "current_response_len": "120"},
        "hits": [{"file": "chunk.abc.js", "marker": "Security Verification", "src": "sitecallback: (t) => …"}],
    }
    joined = "\n".join(deep_scan_lines(deep))
    assert "dialog markup" in joined and "role=dialog" in joined
    assert "getResponse=yes" in joined and "len=120" in joined
    assert "bundle source hits: 1" in joined and "chunk.abc.js" in joined


@pytest.mark.unit
def test_deep_scan_lines_empty_is_safe():
    joined = "\n".join(deep_scan_lines({}))
    assert "(no open dialog)" in joined
    assert "not present on window" in joined
    assert "bundle source hits: 0" in joined
