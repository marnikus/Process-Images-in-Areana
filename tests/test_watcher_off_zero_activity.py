"""S2 · D-23 — Watcher OFF means ZERO captcha activity (the counting test).

One fake stack counts every observable captcha side effect: detect probes,
dialog polls, overlays, `waiting_captcha` pool marks, stats, recordings,
penalties, `🛡` log lines and `CAPTCHA_SOLVE` lines. With the switch OFF the
whole dict is zeros; the positive control (§E.3) proves the same counters
DO count with the switch ON, so the zero test cannot pass vacuously.
RULE 8: real PagePool (wrapped for counting) + the real choke point.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import cooldown_service
from app.services import single_job_runner as sjr
from app.services.captcha import service as captcha_service
from app.services.captcha.service import CaptchaCtx, handle_captcha

from tests.characterization.harness import make_block

pytestmark = pytest.mark.unit

COUNTERS = ("detect_probes", "dialog_polls", "overlays", "mark_waiting", "stats",
            "recordings", "penalties", "shield_lines", "captcha_solve_lines")


class CountingPool(PagePool):
    def __init__(self, counts):
        super().__init__()
        self._counts = counts

    def mark_waiting(self, tab_id, kind):
        if kind == "captcha":  # the generation wait's own mark is not captcha activity
            self._counts["mark_waiting"] += 1
        return super().mark_waiting(tab_id, kind)


class Stack:
    """Bridge + ctrl + counters for one scripted dialog (visible_times=None ⇒ forever)."""

    def __init__(self, monkeypatch, *, watcher_on: bool, visible_times=None):
        self.counts = {k: 0 for k in COUNTERS}
        self.visible_left = visible_times
        self.session = {"watcher_enabled": watcher_on, "watcher_captcha_timeout_sec": 300,
                        "cooldown_enabled": True, "cooldown_captcha_penalty_seconds": 900}
        self.pool = CountingPool(self.counts)
        self.pool.add_page(PageInfo(ws_url="ws://t1", tab_id="t1", title="T", url="https://arena.ai",
                                    status=PageStatus.STEADY, is_connected=True))
        self.pool.mark_busy("t1", "j1")
        self.logs = []
        self.bridge = _Bridge(self)
        self.svc = SimpleNamespace(
            stats=SimpleNamespace(record=lambda *a: self._count("stats")),
            recordings=SimpleNamespace(start=self._rec, finish=self._rec, abort=self._rec),
            keys=SimpleNamespace(load=lambda: SimpleNamespace(api_key="")),
        )
        self.ctrl = SimpleNamespace(
            is_security_dialog_visible=self._visible,
            cdp=SimpleNamespace(evaluate=self._evaluate),
            show_watcher_overlay=self._overlay, hide_watcher_overlay=self._noop,
            capture_baseline=self._baseline, attach_image=self._ok, insert_prompt=self._ok,
            submit=self._ok, wait_for_new_output=self._wait, download_image=self._download,
        )
        monkeypatch.setattr(cooldown_service, "note_captcha_event",
                            lambda *a, **k: self._count("penalties") or 0)

        async def fast(_s):
            return None
        monkeypatch.setattr(asyncio, "sleep", fast)

    def _count(self, key):
        self.counts[key] += 1

    def _log(self, msg, level="info"):
        self.logs.append((msg, level))
        if "🛡" in msg:
            self._count("shield_lines")
        if "CAPTCHA_SOLVE" in msg:
            self._count("captcha_solve_lines")

    async def _rec(self, *a, **k):
        self._count("recordings")
        return None

    async def _visible(self):
        self._count("dialog_polls")
        if self.visible_left is None:
            return True
        if self.visible_left > 0:
            self.visible_left -= 1
            return True
        return False

    async def _evaluate(self, js):
        self._count("detect_probes")
        return {"visible": True, "kind": "recaptcha_v2", "sitekey": "k", "page_url": "https://arena.ai"}

    async def _overlay(self, *a, **k):
        if k.get("kind") == "captcha":  # the generation overlay is not captcha activity
            self._count("overlays")

    async def _noop(self, *a, **k):
        return None

    async def _baseline(self):
        return {"output_count": 0, "output_srcs": []}

    async def _ok(self, *a, **k):
        return True, "ok"

    async def _wait(self, *a, **k):
        return "completed", {"new_src": "https://x/new.png"}

    async def _download(self, src):
        return True, b"z" * 200, "image/png"

    def stop_requested(self) -> bool:
        """A wait that should never have started is cut after 50 polls, so a
        regression FAILS on the counters instead of hanging the suite."""
        return self.counts["dialog_polls"] >= 50

    def captcha_ctx(self):
        return CaptchaCtx(ctrl=self.ctrl, pool=self.pool, bridge=self.bridge, tab_id="t1",
                          source="check-security", stop=self.stop_requested)

    def job_ctx(self, tmp_path):
        p = tmp_path / "in.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 120)
        img = SimpleNamespace(absolute_path=str(p), relative_path="in.png", status="pending",
                              output_path=None, error=None)
        return sjr.JobCtx(bridge=self.bridge, ctrl=self.ctrl, client=SimpleNamespace(), tab_id="t1",
                          img=img, urls=[], job_id="j1", corr_id="c1", final_prompt="p",
                          baseline={"output_count": 0, "output_srcs": []})


class _Bridge:
    """Bridge stand-in whose `_cancel_requested` trips after 50 dialog polls."""

    def __init__(self, stack: Stack):
        self._stack = stack
        self.config = SimpleNamespace(get_state=lambda k, d=None: stack.session.get(k, d))
        self._page_pool = stack.pool
        self._log = stack._log
        self._emit_pool_status = lambda: None
        self._captcha_service = lambda: stack.svc
        self._emit_job_action_status = lambda a: None
        self.highlight_rect = SimpleNamespace(emit=lambda p: None)
        self.state = SimpleNamespace(settings=SimpleNamespace(
            timeouts={"generation": 180},
            output={"suffix": "_AI", "overwrite": False, "preserve_format": True,
                    "unique_suffix_template": "{base}_AI_{n}{ext}"}))

    @property
    def _cancel_requested(self) -> bool:
        return self._stack.stop_requested()


ZEROS = {k: 0 for k in COUNTERS}


async def test_watcher_off_produces_zero_captcha_side_effects(monkeypatch):
    stack = Stack(monkeypatch, watcher_on=False, visible_times=None)
    outcome = await handle_captcha(stack.captcha_ctx())
    assert outcome.status == "out_of_scope"
    assert stack.counts == ZEROS
    assert not hasattr(stack.ctrl, "pause_clock")  # S3 forward-lock
    assert stack.pool.get_page("t1").status == PageStatus.BUSY


async def test_the_same_counters_do_count_when_on(monkeypatch):
    stack = Stack(monkeypatch, watcher_on=True, visible_times=2)
    outcome = await handle_captcha(stack.captcha_ctx())
    assert outcome.status == "manual"
    c = stack.counts
    assert c["detect_probes"] >= 1 and c["dialog_polls"] >= 1 and c["overlays"] >= 1
    assert c["mark_waiting"] == 1 and c["stats"] >= 2 and c["recordings"] >= 2
    assert c["penalties"] == 1 and c["shield_lines"] >= 1 and c["captcha_solve_lines"] == 1


async def test_zero_activity_holds_through_the_whole_job(monkeypatch, tmp_path):
    stack = Stack(monkeypatch, watcher_on=False, visible_times=None)
    ctx = stack.job_ctx(tmp_path)
    handlers = sjr._handler_map()
    for block_id in ("CHECK_SECURITY", "WAIT_OUTPUT"):
        await handlers[block_id](ctx, make_block(block_id, timeout_ms=1000))
    assert stack.counts == ZEROS
    assert not hasattr(stack.ctrl, "security_settler")
    assert stack.pool.get_page("t1").status != PageStatus.WAITING_CAPTCHA
    assert ctx.img.status != "failed"
    assert captcha_service  # the choke point module stayed importable (no lazy import drift)
