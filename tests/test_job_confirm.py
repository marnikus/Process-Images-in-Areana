"""Chrome step confirmations — every row of design D-3 (2026-09-26).

docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md D-3.
RULE 8: the real confirmation logic, the real probe builder and the real
tracker; only the page (a scripted `evaluate`) and New Chat are faked.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.browser.page_recovery import LinkLost
from app.services.job_flow import confirm as jc
from app.services.job_flow.steps import steps_of

pytestmark = pytest.mark.unit

PROMPT = "a cat [JOB-ID: c1]"
CLEAN = {"composer_len": 0, "prompt_ok": False, "marker_in_composer": False, "previews": [],
         "bubble": False, "send_enabled": False, "generating": False, "errors": ""}
READY = dict(CLEAN, composer_len=len(PROMPT), prompt_ok=True, marker_in_composer=True,
             previews=[{"alt": "cat.png", "blob": True}], send_enabled=True)
SENT = dict(CLEAN, bubble=True)


class Page:
    """Scripted page: one state per read (the last one repeats)."""

    def __init__(self, *states, as_text=False):
        self.states, self.as_text, self.exprs = list(states), as_text, []
        self.is_connected = True

    async def evaluate(self, expr, await_promise=True):
        self.exprs.append(expr)
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return json.dumps(state) if self.as_text and isinstance(state, dict) else state


class Ctrl:
    def __init__(self):
        self.inserted = []

    async def insert_prompt(self, text):
        self.inserted.append(text)
        return True, "ok"


def make_ctx(page, done=("ATTACH_IMAGE", "INSERT_PROMPT")):
    logs = []
    bridge = SimpleNamespace(_log=lambda m, l="info": logs.append((m, l)), logs=logs, _cancel_requested=False)
    ctx = SimpleNamespace(bridge=bridge, ctrl=Ctrl(), client=page, corr_id="c1", final_prompt=PROMPT, steps=None)
    steps_of(ctx).done_blocks.update(done)
    return ctx


@pytest.fixture(autouse=True)
def instant(monkeypatch):
    async def _fast(_s):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast)


def logged(ctx, needle):
    return any(needle in m for m, _ in ctx.bridge.logs)


# ── the probe itself ──

async def test_probe_is_the_shared_composer_state_body_and_text_answers_parse():
    ctx = make_ctx(Page(CLEAN, as_text=True))
    assert await jc.read_state(ctx) == CLEAN
    assert "__previews" in ctx.client.exprs[0] and json.dumps(PROMPT) in ctx.client.exprs[0]


@pytest.mark.parametrize("answer", [None, {"found": True}, "not json", 7])
async def test_unusable_answers_read_as_empty(answer):
    assert await jc.read_state(make_ctx(Page(answer))) == {}


async def test_no_client_and_a_raising_client_read_as_empty():
    ctx = make_ctx(None)
    assert await jc.read_state(ctx) == {}

    class Boom(Page):
        async def evaluate(self, expr, await_promise=True):
            raise RuntimeError("socket")
    assert await jc.read_state(make_ctx(Boom(CLEAN))) == {}


# ── clean start ──

async def test_clean_start_confirms_and_records_the_error_corpus():
    ctx = make_ctx(Page(dict(CLEAN, errors="old toast")))
    assert await jc.confirm_clean_start(ctx) == ""
    assert ctx.steps.err_base == "old toast" and ("clean_start", True) in ctx.steps.trail


async def test_clean_start_without_a_text_area_yet_still_starts():
    ctx = make_ctx(Page(dict(CLEAN, composer_len=-1)))
    assert await jc.confirm_clean_start(ctx) == ""
    assert logged(ctx, "text area not found yet")


async def test_unreadable_start_fails_open():
    ctx = make_ctx(Page(None))
    assert await jc.confirm_clean_start(ctx) == ""
    assert logged(ctx, "⚠ clean_start — composer not readable")


async def test_dirty_start_opens_a_new_chat_then_confirms(monkeypatch):
    resets = []

    async def fake_reset(reset_ctx):
        resets.append(reset_ctx.timeout_sec)
        assert reset_ctx.cancel_check() is False
        return True, "new chat ready"
    monkeypatch.setattr(jc, "reset_to_new_chat", fake_reset)
    ctx = make_ctx(Page(dict(CLEAN, composer_len=12, previews=[{"alt": "old.png"}]), CLEAN))
    assert await jc.confirm_clean_start(ctx) == ""
    assert resets == [jc.RESET_TIMEOUT_S]
    assert logged(ctx, "leftovers in the composer (12 chars of text, 1 attachment preview(s))")
    assert logged(ctx, "✔ clean_start — clean composer after New Chat")


async def test_still_dirty_after_new_chat_fails_the_job_before_anything_is_sent(monkeypatch):
    async def failed_reset(reset_ctx):
        return False, "new-chat button not found"
    monkeypatch.setattr(jc, "reset_to_new_chat", failed_reset)
    dirty = dict(CLEAN, previews=[{"alt": "old.png"}])
    err = await jc.confirm_clean_start(make_ctx(Page(dirty)))
    assert err == "Page not clean at job start (1 attachment preview(s)) — nothing sent, safe to retry"

    async def raising_reset(reset_ctx):
        raise RuntimeError("boom")
    monkeypatch.setattr(jc, "reset_to_new_chat", raising_reset)
    err = await jc.confirm_clean_start(make_ctx(Page(dict(CLEAN, composer_len=3), None)))
    assert err == "Page not clean at job start (page not readable) — nothing sent, safe to retry"


async def test_a_dead_link_at_start_fails_safely():
    page = Page(CLEAN)
    page.is_connected = False          # closed, and no ws url to re-attach to
    err = await jc.confirm_clean_start(make_ctx(page))
    assert err.startswith("CDP connection lost") and err.endswith("nothing sent, safe to retry")


# ── composer before the click ──

async def test_composer_confirmed_after_a_late_preview():
    ctx = make_ctx(Page(dict(READY, previews=[]), READY))
    assert await jc.confirm_composer(ctx) is False
    assert len(ctx.client.exprs) == 2 and logged(ctx, "✔ composer — image preview 1 + exact prompt")


async def test_composer_with_our_message_already_in_the_chat_means_do_not_click():
    ctx = make_ctx(Page(SENT))
    assert await jc.confirm_composer(ctx) is True
    assert logged(ctx, "already in the chat — sent, not clicking again")


async def test_missing_prompt_is_inserted_once_more():
    wrong = dict(READY, prompt_ok=False, composer_len=0)
    ctx = make_ctx(Page(*([wrong] * jc.COMPOSER_TRIES), READY))
    assert await jc.confirm_composer(ctx) is False
    assert ctx.ctrl.inserted == [PROMPT] and logged(ctx, "inserting it again")


async def test_prompt_still_wrong_after_the_reinsert_fails_nothing_sent():
    ctx = make_ctx(Page(dict(READY, prompt_ok=False, composer_len=5)))

    async def broken_insert(text):
        raise RuntimeError("textarea gone")
    ctx.ctrl.insert_prompt = broken_insert
    with pytest.raises(RuntimeError, match=r"does not hold the prompt \(5 chars\) — nothing sent, safe to retry"):
        await jc.confirm_composer(ctx)
    assert logged(ctx, "re-insert failed: textarea gone")


async def test_missing_image_preview_fails_nothing_sent():
    ctx = make_ctx(Page(dict(READY, previews=[])))
    with pytest.raises(RuntimeError, match="image preview is not in the composer — nothing sent"):
        await jc.confirm_composer(ctx)
    assert len(ctx.client.exprs) == jc.COMPOSER_TRIES


async def test_only_what_the_stack_did_is_required():
    ctx = make_ctx(Page(CLEAN), done=())
    assert await jc.confirm_composer(ctx) is False


async def test_unreadable_composer_fails_open():
    ctx = make_ctx(Page(None))
    assert await jc.confirm_composer(ctx) is False
    assert logged(ctx, "not confirmed, sending anyway")


async def test_a_fresh_page_error_before_the_click_fails_the_step():
    ctx = make_ctx(Page(dict(READY, previews=[], errors="Rate limit exceeded")))
    ctx.steps.err_base = ""
    with pytest.raises(RuntimeError, match=r"Page error: Rate limit exceeded \(before submit — nothing sent"):
        await jc.confirm_composer(ctx)


async def test_a_stale_error_line_is_not_fresh():
    ctx = make_ctx(Page(dict(READY, errors="Rate limit exceeded")))
    ctx.steps.err_base = "Rate limit exceeded"
    assert await jc.confirm_composer(ctx) is False


async def test_without_a_start_corpus_the_first_read_becomes_it():
    ctx = make_ctx(Page(dict(READY, errors="Rate limit exceeded")))
    assert await jc.confirm_composer(ctx) is False
    assert ctx.steps.err_base == "Rate limit exceeded"


# ── the send after the click ──

@pytest.mark.parametrize("state,how", [
    (SENT, "JOB-ID message visible in the chat"),
    (dict(CLEAN, generating=True, composer_len=4), "generation running"),
    (CLEAN, "composer cleared"),
])
async def test_send_confirmed_by_page_evidence(state, how):
    ctx = make_ctx(Page(READY, state))
    assert await jc.confirm_sent(ctx) == how
    assert logged(ctx, f"✔ sent — new job started ({how})")


async def test_prompt_still_in_the_composer_means_not_delivered():
    ctx = make_ctx(Page(READY))
    with pytest.raises(RuntimeError, match="Submit not delivered — the prompt is still in the composer"):
        await jc.confirm_sent(ctx)
    assert len(ctx.client.exprs) == jc.SEND_TRIES


async def test_changed_composer_without_proof_leaves_it_to_the_wait():
    ctx = make_ctx(Page(dict(CLEAN, composer_len=3)))
    assert await jc.confirm_sent(ctx) == ""
    assert logged(ctx, "watching for the result")


async def test_unreadable_send_is_left_to_the_wait():
    ctx = make_ctx(Page(None))
    assert await jc.confirm_sent(ctx) == ""


async def test_a_fresh_page_error_after_the_click_fails_the_step():
    ctx = make_ctx(Page(dict(CLEAN, composer_len=3, errors="Something went wrong")))
    ctx.steps.err_base = ""
    with pytest.raises(RuntimeError, match=r"^Page error: Something went wrong \(after submit\)$"):
        await jc.confirm_sent(ctx)


# ── saved on disk ──

def test_saved_file_is_proven_on_disk(tmp_path):
    ctx = make_ctx(Page(CLEAN))
    out = tmp_path / "cat_AI.png"
    out.write_bytes(b"x" * 10)
    jc.confirm_saved(ctx, out, 10)
    assert logged(ctx, "✔ saved_on_disk — cat_AI.png · 10 bytes")
    with pytest.raises(RuntimeError, match=r"Save not confirmed: 10/11 bytes on disk \(cat_AI.png\)"):
        jc.confirm_saved(ctx, out, 11)
    with pytest.raises(RuntimeError, match="Save not confirmed: .*No such file"):
        jc.confirm_saved(ctx, tmp_path / "missing.png", 1)


async def test_a_closed_link_is_healed_before_the_read(monkeypatch):
    page = Page(READY)
    page.is_connected = False
    page._current_ws_url = "ws://127.0.0.1:9222/devtools/page/T1"

    async def connect(url):
        page.is_connected = True
        return True
    page.connect = connect

    async def answers(cdp, report=None, **kw):
        await cdp.connect(cdp._current_ws_url)
        return True
    monkeypatch.setattr("app.browser.page_recovery.recover_page_context", answers)
    assert await jc.read_state(make_ctx(page)) == READY


async def test_link_lost_propagates_from_the_composer_check():
    page = Page(READY)
    page.is_connected = False
    with pytest.raises(LinkLost):
        await jc.confirm_composer(make_ctx(page))
