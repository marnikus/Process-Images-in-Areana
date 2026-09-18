"""Captcha wait visibility (2026-09-18 captcha-wait-visibility).

Regression: during the WAIT_OUTPUT block the per-poll security gate
(CDPArenaController._security_gate) was a SILENT NO-OP — the bridge block
runner never armed ctrl.security_settler, so a captcha dialog opening during
the generation wait produced zero logs and zero solve attempts. And the gate
predicate was a bare boolean: no record of WHAT was on the page.

Now: the bridge arms the settler for its wait paths, the gate evaluates the
diagnose probe (verdict + evidence + reason), logs verdict changes / a ~30 s
heartbeat / a no-settler warning, and the on-demand "Scan now" builds a
numbered report. Docs: docs/archive/2026-09-18-captcha-wait-visibility/design.md
"""

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from app.browser.cdp_arena import CDPArenaController
from app.persistence.config_manager import ConfigManager
from app.services.captcha.diagnose import build_scan_report
from app.ui.bridge import Bridge

CLEAR = {"visible": False, "evidence": {"reason": "no open dialog; 1 recaptcha iframe(s) — 1 in badge, 0 hidden/off-screen"}}
CHALLENGE = {
    "visible": True, "kind": "recaptcha_enterprise", "sitekey": "6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL",
    "evidence": {"reason": "open dialog: Security Verification, Protected by reCAPTCHA, widget"},
}


class FakeCdp:
    def __init__(self, result: Any = None, error: Exception = None):
        self.result = result
        self.error = error
        self.calls = 0

    async def evaluate(self, js: str, *a, **k):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def make_ctrl(result: Any = None, error: Exception = None, logs: List[str] = None) -> CDPArenaController:
    return CDPArenaController(FakeCdp(result, error), log_callback=logs.append if logs is not None else None)


def make_bridge(tmp_path) -> Bridge:
    cfg = ConfigManager(config_dir=str(tmp_path / "config"))
    return Bridge(cfg, tmp_path / "app_state.json")


@pytest.mark.unit
async def test_gate_clear_logs_verdict_and_heartbeats():
    logs: List[str] = []
    ctrl = make_ctrl(CLEAR, logs=logs)
    for _ in range(CDPArenaController._SEC_BEAT_EVERY):
        await ctrl._security_gate()
    verdict_lines = [l for l in logs if "Security scan" in l]
    assert any("clear" in l for l in verdict_lines)          # verdict change on first poll
    assert any(l.startswith("🔎") for l in verdict_lines)     # ~30 s heartbeat on the 15th
    assert not any("no auto-settle armed" in l for l in logs)  # no warning while clear


@pytest.mark.unit
async def test_gate_challenge_without_settler_warns_once():
    logs: List[str] = []
    ctrl = make_ctrl(CHALLENGE, logs=logs)
    for _ in range(3):
        await ctrl._security_gate()
    assert sum("no auto-settle armed" in l for l in logs) == 1  # one per episode, never silent
    assert any("challenge" in l for l in logs)


@pytest.mark.unit
async def test_gate_challenge_calls_settler_then_stops_when_clear():
    logs: List[str] = []
    calls = []
    cdp = FakeCdp(CHALLENGE)
    ctrl = CDPArenaController(cdp, log_callback=logs.append)

    async def settle():
        calls.append(1)

    ctrl.security_settler = settle
    await ctrl._security_gate()
    assert calls == [1]
    cdp.result = CLEAR  # dialog solved → next poll clear, no re-settle
    await ctrl._security_gate()
    assert calls == [1]


@pytest.mark.unit
async def test_gate_probe_error_fails_open():
    logs: List[str] = []
    ctrl = make_ctrl(None, error=RuntimeError("tab crashed"), logs=logs)
    await ctrl._security_gate()  # must not raise (RULE 9)
    assert any("probe error" in l for l in logs)


@pytest.mark.unit
async def test_gate_settler_exception_is_warned_not_raised():
    logs: List[str] = []
    ctrl = make_ctrl(CHALLENGE, logs=logs)

    async def settle():
        raise RuntimeError("user stopped during solve")

    ctrl.security_settler = settle
    await ctrl._security_gate()
    assert any("Security gate settle failed" in l for l in logs)


@pytest.mark.unit
async def test_arm_gen_wait_settler_wires_settle_and_overlay(tmp_path):
    bridge = make_bridge(tmp_path)
    settled, overlays = [], []

    async def fake_settle(ctrl, tab_id, corr_id, source):
        settled.append((tab_id, corr_id, source))

    bridge._settle_captcha_at = fake_settle
    ctrl = SimpleNamespace()

    async def fake_overlay(msg, kind, timeout_sec):
        overlays.append((msg, kind, timeout_sec))

    ctrl.show_watcher_overlay = fake_overlay
    bridge._arm_gen_wait_settler(ctrl, "tab-123", "Q4DB")
    await ctrl.security_settler()
    assert settled == [("tab-123", "Q4DB", "gen-wait")]
    assert overlays and overlays[0][:2] == ("wait for finish generation", "generation")


@pytest.mark.unit
def test_scan_report_challenge_lines():
    status = {"enabled": True, "has_key": True, "masked_key": "abc…", "last_error": None}
    lines = build_scan_report(CHALLENGE, "https://arena.ai", status)
    joined = "\n".join(lines)
    assert "step by step on https://arena.ai" in joined
    assert "1. open dialogs" in joined
    assert "2. reCAPTCHA iframes" in joined
    assert "CHALLENGE VISIBLE" in joined
    assert "kind=recaptcha_enterprise" in joined and "sitekey=set" in joined
    assert "auto-solve: ON" in joined and "abc…" in joined
    assert "5. action:" in joined


@pytest.mark.unit
def test_scan_report_clear_lines_and_frame_evidence():
    info = {
        "visible": False,
        "evidence": {"dialogs_open": 0, "dialog_hits": [],
                     "iframes": [{"in_badge": True, "in_dialog": False, "on_screen": False,
                                  "w": 256, "h": 60, "x": -186, "y": 840, "title": "reCAPTCHA", "src": ""}],
                     "reason": "no open dialog; 1 recaptcha iframe(s) — 1 in badge, 0 hidden/off-screen"},
    }
    lines = build_scan_report(info, "", {"enabled": False, "has_key": False, "masked_key": None})
    joined = "\n".join(lines)
    assert "no challenge" in joined
    assert "in badge hidden/off-screen" in joined
    assert "auto-solve: OFF" in joined
    assert "key (not set)" in joined
    assert "nothing to solve" in joined


@pytest.mark.unit
def test_bridge_diagnose_slot_without_browser(tmp_path):
    bridge = make_bridge(tmp_path)
    r = json.loads(bridge.diagnose_captcha())
    assert r["ok"] is False and "not connected" in r["error"]
