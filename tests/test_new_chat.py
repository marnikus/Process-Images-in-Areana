"""Tests for app/browser/new_chat.py — post-generation reset.

RULE 8: executes the real orchestration; only CDP boundary scripted via
small fakes + monkeypatched visual runner. No real sleeps (short timeouts).
"""

import pytest

from app.browser import new_chat as nc


class FakeCtrl:
    def __init__(self, ready_seq=None):
        self.ready_seq = list(ready_seq or [(True, [])])
        self.calls = 0

    async def is_page_ready(self):
        self.calls += 1
        if len(self.ready_seq) > 1:
            return self.ready_seq.pop(0)
        return self.ready_seq[0]


class FakeClient:
    def __init__(self, loaded=True, empty_seq=None):
        self.loaded = loaded
        self.empty_seq = list(empty_seq if empty_seq is not None else [True])
        self.exprs = []

    async def evaluate(self, expr, await_promise=True):
        self.exprs.append(expr)
        if "readyState" in expr:
            state = "complete" if self.loaded else "loading"
            return {"complete": self.loaded, "readyState": state, "hasTextarea": True}
        if len(self.empty_seq) > 1:
            empty = self.empty_seq.pop(0)
        else:
            empty = self.empty_seq[0]
        return {"empty": empty, "len": 0 if empty else 42}


class FakeEngine:
    def __init__(self):
        self.records = []

    def report(self, message, level="info"):
        self.records.append((message, level))


def make_ctx(ctrl=None, client=None, engine=None, timeout=5, cancel=None):
    return nc.ResetCtx(ctrl=ctrl or FakeCtrl(), client=client or FakeClient(),
                       engine=engine or FakeEngine(), timeout_sec=timeout,
                       cancel_check=cancel)


@pytest.mark.unit
def test_candidates_semantic_first_no_tailwind():
    assert len(nc.NEW_CHAT_CANDIDATES) >= 2
    first = nc.NEW_CHAT_CANDIDATES[0]
    assert first[0] == 'a[href="/image/direct"]'
    assert "New Chat" in first
    for sel, _, _ in nc.NEW_CHAT_CANDIDATES:
        assert "flex" not in sel and "w-5" not in sel  # RULE 21: no class soup


@pytest.mark.unit
def test_js_builders_probe_load_and_composer():
    loaded_js = nc.build_page_loaded_js()
    assert "readyState" in loaded_js
    assert "textarea" in loaded_js
    empty_js = nc.build_composer_empty_js()
    assert "value" in empty_js
    assert "message" in empty_js


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_success_clicks_and_waits_loaded(monkeypatch):
    seen = []

    async def fake_click(client, req, engine=None):
        seen.append(req.selector)
        return "ok"

    monkeypatch.setattr(nc, "find_and_click", fake_click)
    engine = FakeEngine()
    ctx = make_ctx(engine=engine)
    ok, reason = await nc.reset_to_new_chat(ctx)
    assert ok is True
    assert seen == ['a[href="/image/direct"]']  # primary wins first try
    assert any("New Chat" in m for m, _ in engine.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_tries_fallbacks_in_order(monkeypatch):
    seen = []

    async def fake_click(client, req, engine=None):
        seen.append(req.selector)
        return "ok" if len(seen) == 3 else "not-found"

    monkeypatch.setattr(nc, "find_and_click", fake_click)
    ctx = make_ctx()
    ok, _ = await nc.reset_to_new_chat(ctx)
    assert ok is True
    assert len(seen) == 3
    assert seen[0] == 'a[href="/image/direct"]'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_fails_when_button_missing(monkeypatch):
    async def fake_click(client, req, engine=None):
        return "not-found"

    monkeypatch.setattr(nc, "find_and_click", fake_click)
    ctx = make_ctx()
    ok, reason = await nc.reset_to_new_chat(ctx)
    assert ok is False
    assert "not found" in reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_waits_for_composer_to_empty(monkeypatch):
    async def fake_click(client, req, engine=None):
        return "ok"

    monkeypatch.setattr(nc, "find_and_click", fake_click)
    client = FakeClient(loaded=True, empty_seq=[False, False, True])
    ctx = make_ctx(client=client, timeout=5)
    ok, _ = await nc.reset_to_new_chat(ctx)
    assert ok is True
    assert ctx.ctrl.calls >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_timeout_when_never_loaded(monkeypatch):
    async def fake_click(client, req, engine=None):
        return "ok"

    monkeypatch.setattr(nc, "find_and_click", fake_click)
    ctx = make_ctx(client=FakeClient(loaded=False), timeout=0.2)
    ok, reason = await nc.reset_to_new_chat(ctx)
    assert ok is False
    assert "timeout" in reason.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_honours_cancel(monkeypatch):
    async def fake_click(client, req, engine=None):
        return "ok"  # pragma: no cover - cancel hits first

    monkeypatch.setattr(nc, "find_and_click", fake_click)
    ctx = make_ctx(client=FakeClient(loaded=False), timeout=5, cancel=lambda: True)
    ok, reason = await nc.reset_to_new_chat(ctx)
    assert ok is False
    assert "cancel" in reason.lower()


@pytest.mark.unit
def test_fresh_chat_ready_rule():
    assert nc._fresh_chat_ready(True, []) is True
    assert nc._fresh_chat_ready(False, ["file not visible", "output not found"]) is True
    assert nc._fresh_chat_ready(False, ["output not found"]) is True
    assert nc._fresh_chat_ready(False, ["prompt not found"]) is False
    assert nc._fresh_chat_ready(False, ["send not visible", "output not found"]) is False
    assert nc._fresh_chat_ready(False, ["Security dialog"]) is False
    assert nc._fresh_chat_ready(False, []) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_accepts_fresh_chat_without_output(monkeypatch):
    # user log 2026-09-16: fresh new chat has no file/output yet — not failure
    async def fake_click(client, req, engine=None):
        return "ok"

    monkeypatch.setattr(nc, "find_and_click", fake_click)
    ctrl = FakeCtrl(ready_seq=[(False, ["file not visible", "output not found"])])
    ctx = make_ctx(ctrl=ctrl, timeout=5)
    ok, reason = await nc.reset_to_new_chat(ctx)
    assert ok is True
    assert reason == "new chat ready"
