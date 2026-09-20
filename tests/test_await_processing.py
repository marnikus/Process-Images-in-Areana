"""AWAIT_PROCESSING_IMAGE handler + processing probe builders (B12).

Field case (bugfix-verification.md §B12): the block ran the WAIT_OUTPUT
new-output wait; sitting before ATTACH_IMAGE in the default stack it waited
the full 120 s on every idle page — "the first run starts without pasting
image and prompt and waits for a generation that never starts".

RULE 8: the REAL handler and REAL builders run; only the CDP client, the
controller and the bridge are stand-ins. The generated JS is executed for
real in tests/js/test_processing_probe.mjs (jsdom).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.browser import processing_probe as pp
from app.core.action_blocks import BLOCK_DEFINITIONS
from app.core.action_blocks_defaults import build_default_stack
from app.services import await_processing as ap
from tests.characterization.harness import make_block
from tests.test_single_job_runner import instant_sleep, make_bridge, make_ctrl, make_ctx, make_img

pytestmark = pytest.mark.unit

DEFAULT_SEL = BLOCK_DEFINITIONS["AWAIT_PROCESSING_IMAGE"]["default_selector"]


def scripted_client(replies):
    """CDP stand-in: each evaluate pops the next reply (last one repeats)."""
    calls = []

    async def _eval(js):
        calls.append(js)
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    return SimpleNamespace(evaluate=_eval, calls=calls)


def busy(*inds):
    return json.dumps({"processing": True, "indicators": list(inds) or [{"kind": "spinner", "sel": "div.animate-spin", "text": ""}]})


IDLE = json.dumps({"processing": False, "indicators": []})


def overlay_recorder(**kw):
    seen = []

    async def _show(message, kind="generation", timeout_sec=0, sub=""):
        seen.append(("show", message, kind, timeout_sec))
        return True

    async def _hide():
        seen.append(("hide",))
        return True

    ctrl = make_ctrl(show_watcher_overlay=_show, hide_watcher_overlay=_hide, **kw)
    ctrl.overlay = seen
    return ctrl


# ---- the default stack really is the field case ----

def test_default_stack_puts_the_await_block_before_attach():
    ids = [b.block_id for b in build_default_stack()]
    assert ids.index("AWAIT_PROCESSING_IMAGE") < ids.index("ATTACH_IMAGE")
    blk = next(b for b in build_default_stack() if b.block_id == "AWAIT_PROCESSING_IMAGE")
    assert blk.enabled and not blk.required and blk.timeout_ms == 120000


# ---- handler ----

@pytest.mark.asyncio
async def test_idle_page_continues_at_once(tmp_path, monkeypatch):
    sleeps = []

    async def _sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    bridge = make_bridge()
    client = scripted_client([IDLE])
    ctrl = overlay_recorder()
    ctx = make_ctx(bridge, ctrl, client, make_img(tmp_path))
    await ap.handle_await_processing(ctx, make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=120000))
    assert [(e[0], e[1]) for e in bridge._events] == [("AWAIT_PROCESSING_IMAGE", "success")]
    assert "Page idle" in bridge._events[0][2]
    assert sleeps == [] and len(client.calls) == 1
    assert ctrl.overlay == [], "no generation overlay on an idle page"
    assert "processing" in client.calls[0] and json.dumps("div.animate-spin") in client.calls[0]


@pytest.mark.asyncio
async def test_busy_page_waits_until_the_indicator_is_gone(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    bridge = make_bridge()
    client = scripted_client([busy(), busy(), IDLE])
    ctrl = overlay_recorder()
    ctx = make_ctx(bridge, ctrl, client, make_img(tmp_path))
    blk = make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=120000, extra={"poll_interval_ms": 300})
    await ap.handle_await_processing(ctx, blk)
    statuses = [e[1] for e in bridge._events]
    assert statuses == ["waiting", "success"]
    assert "spinner div.animate-spin" in bridge._events[0][2]
    assert "Processing finished" in bridge._events[1][2]
    assert len(client.calls) == 3
    assert ctrl.overlay[0][:3] == ("show", ap.OVERLAY_MESSAGE, "generation")
    assert ctrl.overlay[-1] == ("hide",)
    assert any("waiting up to 120000 ms" in m for m, _l in bridge._logs)


@pytest.mark.asyncio
async def test_timeout_never_fails_the_job(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    bridge = make_bridge()
    client = scripted_client([busy()])
    ctx = make_ctx(bridge, overlay_recorder(), client, make_img(tmp_path))
    blk = make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=1)
    monkeypatch.setattr(ap.time, "monotonic", _ticking(seconds=[0.0, 5.0, 10.0, 15.0]))
    await ap.handle_await_processing(ctx, blk)   # must not raise
    assert [e[1] for e in bridge._events] == ["waiting", "success"]
    assert "Still busy after 1 ms" in bridge._events[-1][2]
    assert any(lvl == "warn" and "never fails a job" in m for m, lvl in bridge._logs)


def _ticking(seconds):
    it = iter(seconds)
    last = [seconds[-1]]

    def _now():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return _now


@pytest.mark.asyncio
async def test_cancel_stops_the_wait_as_skipped(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    bridge = make_bridge()
    client = scripted_client([busy()])
    ctx = make_ctx(bridge, overlay_recorder(), client, make_img(tmp_path))

    async def _sleep_then_cancel(_s):
        bridge._cancel_requested = True

    monkeypatch.setattr(asyncio, "sleep", _sleep_then_cancel)
    await ap.handle_await_processing(ctx, make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=120000))
    assert [e[1] for e in bridge._events] == ["waiting", "skipped"]


@pytest.mark.asyncio
async def test_tab_abort_counts_as_cancel(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    pool = SimpleNamespace(_aborts={"t1"}, mark_waiting=lambda *a: True, mark_busy=lambda *a: True)
    bridge = make_bridge(pool=pool)
    ctx = make_ctx(bridge, overlay_recorder(), scripted_client([busy()]), make_img(tmp_path))
    await ap.handle_await_processing(ctx, make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=120000))
    assert [e[1] for e in bridge._events] == ["waiting", "skipped"]


@pytest.mark.asyncio
async def test_broken_probe_reads_as_idle(tmp_path, monkeypatch):
    """A probe that raises / answers nothing must not stall the run (that stall IS the bug)."""
    instant_sleep(monkeypatch)
    for reply in (RuntimeError("Cannot find context"), None, "", "not json", json.dumps([1, 2])):
        bridge = make_bridge()
        ctx = make_ctx(bridge, overlay_recorder(), scripted_client([reply]), make_img(tmp_path))
        await ap.handle_await_processing(ctx, make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=120000))
        assert [e[1] for e in bridge._events] == ["success"], repr(reply)
        assert "Page idle" in bridge._events[0][2]


@pytest.mark.asyncio
async def test_pool_row_waits_then_busy_again(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    marks = []
    pool = SimpleNamespace(_aborts=set(),
                           mark_waiting=lambda tab, kind: marks.append(("waiting", tab, kind)),
                           mark_busy=lambda tab, job: marks.append(("busy", tab, job)))
    bridge = make_bridge(pool=pool)
    ctx = make_ctx(bridge, overlay_recorder(), scripted_client([busy(), IDLE]), make_img(tmp_path))
    await ap.handle_await_processing(ctx, make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=120000))
    assert marks == [("waiting", "t1", "generation"), ("busy", "t1", "j1")]
    assert ("pool", "") in bridge._logs


@pytest.mark.asyncio
async def test_bridge_and_overlay_failures_are_swallowed(tmp_path, monkeypatch):
    """A throwing emitter / logger / overlay never breaks the wait itself."""
    instant_sleep(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("bridge gone")

    async def _aboom(*a, **k):
        raise RuntimeError("overlay gone")

    bridge = make_bridge()
    bridge._emit_job_action_status = _boom
    bridge._log = _boom
    ctrl = make_ctrl(show_watcher_overlay=_aboom, hide_watcher_overlay=_aboom)
    client = scripted_client([busy(), IDLE])
    ctx = make_ctx(bridge, ctrl, client, make_img(tmp_path))
    await ap.handle_await_processing(ctx, make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=120000))
    assert len(client.calls) == 2, "the poll loop ran to idle despite the failing side channels"


def test_poll_and_timeout_defaults_and_clamps():
    assert ap.poll_seconds(make_block("AWAIT_PROCESSING_IMAGE")) == 1.0
    assert ap.poll_seconds(make_block("AWAIT_PROCESSING_IMAGE", extra={"poll_interval_ms": 10})) == 0.25
    assert ap.poll_seconds(make_block("AWAIT_PROCESSING_IMAGE", extra={"poll_interval_ms": 99999})) == 5.0
    assert ap.poll_seconds(make_block("AWAIT_PROCESSING_IMAGE", extra={"poll_interval_ms": "x"})) == 1.0
    assert ap.timeout_ms(make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=0)) == 120000
    assert ap.timeout_ms(SimpleNamespace(timeout_ms="bad")) == 120000
    assert ap.describe({"indicators": []}) == "indicator"
    assert ap.describe({"indicators": [{"kind": "text", "sel": "span", "text": "Processing…"}]}) == "text span 'Processing…'"


# ---- probe builders ----

def test_selector_parts_translate_has_text_and_keep_css():
    parts = pp.selector_parts(DEFAULT_SEL)
    assert parts == [
        {"sel": "div", "text": "processing"},
        {"sel": "div", "text": "generating"},
        {"sel": '[data-state="loading"]', "text": ""},
        {"sel": ".spinner", "text": ""},
        {"sel": '[aria-busy="true"]', "text": ""},
    ]
    assert pp.selector_parts(':has-text("Busy")') == [{"sel": "*", "text": "busy"}]
    assert pp.selector_parts("span:has-text('A, b') i") == [{"sel": "span i", "text": "a, b"}]
    assert pp.selector_parts("") == []


def test_split_selector_list_respects_quotes_and_nesting():
    assert pp.split_selector_list('a:is(b, c), d[x="1,2"], e') == ["a:is(b, c)", 'd[x="1,2"]', "e"]
    assert pp.split_selector_list(" , x ,, ") == ["x"]


def test_probe_payload_carries_site_spinner_parts_and_text():
    js = pp.build_processing_probe(DEFAULT_SEL, "  Processing ")
    assert json.dumps("div.animate-spin") in js
    assert json.dumps(pp.selector_parts(DEFAULT_SEL)) in js
    assert json.dumps("processing") in js
    assert ":has-text" not in js  # translated into {sel, text} parts, never sent as CSS
    assert "__SPINNER__" not in js and "__PARTS__" not in js and "__MATCH_TEXT__" not in js


def test_interpret_processing_shapes():
    assert pp.interpret_processing(json.dumps({"processing": True, "indicators": [1]}))["processing"] is True
    assert pp.interpret_processing({"processing": 0})["processing"] is False
    assert pp.interpret_processing(None) == {"processing": False, "indicators": [], "reason": "no_result"}
    assert pp.interpret_processing("{oops")["reason"] == "unparseable"
    assert pp.interpret_processing(b'{"processing": true}')["processing"] is True
