"""Chrome job step confirmations over CDP (2026-09-26).

docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md D-3.

One page read — `job_scripts.composer_state_js` (the Firefox prelude, reused) —
answers: text in the composer, is it exactly our prompt, attachment previews,
the JOB-ID message in the chat, send enabled, generating, page-error corpus.
Python decides here:

* `confirm_clean_start` — before the first block: empty composer, no preview;
  leftovers → New Chat once → re-check; still dirty → the job fails (nothing sent);
* `confirm_composer` — SUBMIT, before the click: our preview + our exact prompt
  (one re-insert), or the JOB-ID message is already in the chat (never click twice);
* `confirm_sent` — after the click: JOB-ID message / cleared composer / generating;
  the prompt still in the composer = not delivered (safe failure);
* `confirm_saved` — the saved file exists with every byte.

A fresh page-error line (vs the corpus at job start) fails the step. An
unreadable probe fails OPEN with one warning (RULE 9); a closed socket is
healed first (`page_recovery.heal_link`) and `LinkLost` fails the step.
Imports: browser + `job_flow.steps`; never Qt.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Callable

from app.browser.new_chat import ResetCtx, reset_to_new_chat
from app.browser.page_recovery import LinkLost, heal_link
from app.browser.uivision.job_scripts import composer_state_js
from app.services.job_flow.steps import JobSteps, steps_of
from app.utils.page_errors import match_page_error

POLL_S = 0.5
COMPOSER_TRIES = 6      # ≈ 3 s for a late preview / React state
SEND_TRIES = 16         # ≈ 8 s for the send to show
RESET_TIMEOUT_S = 30.0
_PROMPT_BLOCKS = frozenset({"INSERT_PROMPT", "VERIFY_PROMPT"})


def _as_dict(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


async def read_state(ctx) -> dict:
    """One composer read; {} when the page gave no usable answer. LinkLost propagates."""
    client = getattr(ctx, "client", None)
    if client is None:
        return {}
    steps = steps_of(ctx)
    await heal_link(client, lambda m, l="info": steps.log(m, l))
    try:
        data = _as_dict(await client.evaluate(composer_state_js(ctx.corr_id, ctx.final_prompt)))
    except Exception:
        return {}
    return data if "composer_len" in data else {}


async def _poll(ctx, done: Callable[[dict], object], tries: int) -> dict:
    """Read until `done(state)` or `tries` reads; {} at once when unreadable."""
    state = {}
    for attempt in range(tries):
        state = await read_state(ctx)
        if not state or done(state):
            return state
        if attempt + 1 < tries:
            await asyncio.sleep(POLL_S)
    return state


def _raise_page_error(steps: JobSteps, state: dict, sent: bool) -> None:
    """A page-error line that was not there at job start fails the step."""
    corpus = str(state.get("errors") or "")
    if steps.err_base is None:
        steps.err_base = corpus
        return
    err = match_page_error(corpus, steps.err_base)
    if err:
        raise RuntimeError(f"{err} (after submit)" if sent else f"{err} (before submit — nothing sent, safe to retry)")


def _leftovers(state: dict) -> str:
    bits = []
    if int(state.get("composer_len", 0) or 0) > 0:
        bits.append(f"{state.get('composer_len')} chars of text")
    if state.get("previews"):
        bits.append(f"{len(state['previews'])} attachment preview(s)")
    return ", ".join(bits)


async def _new_chat(ctx) -> str:
    """The New-chat reset for a dirty start; '' or its failure text."""
    reset = ResetCtx(ctrl=ctx.ctrl, client=ctx.client, engine=ctx.bridge, timeout_sec=RESET_TIMEOUT_S,
                     cancel_check=lambda: bool(getattr(ctx.bridge, "_cancel_requested", False)))
    try:
        ok, why = await reset_to_new_chat(reset)
    except Exception as exc:
        return str(exc)
    return "" if ok else why


async def _clean_after_reset(ctx, steps: JobSteps, dirt: str) -> str:
    """Dirty start: New Chat once, read again; '' when clean, else the failure text."""
    steps.warn("clean_start", f"leftovers in the composer ({dirt}) — opening a new chat first")
    why = await _new_chat(ctx)
    state = await read_state(ctx)
    if state and not _leftovers(state):
        steps.err_base = str(state.get("errors") or "")
        steps.confirm("clean_start", "clean composer after New Chat")
        return ""
    left = _leftovers(state) if state else "page not readable"
    return f"Page not clean at job start ({left or why}) — nothing sent, safe to retry"


async def confirm_clean_start(ctx) -> str:
    """'' when the job may start (clean, or unreadable = fail open), else why not."""
    steps = steps_of(ctx)
    try:
        state = await read_state(ctx)
    except LinkLost as exc:
        return f"{exc} — nothing sent, safe to retry"
    if not state:
        steps.warn("clean_start", "composer not readable — not confirmed, continuing")
        return ""
    steps.err_base = str(state.get("errors") or "")
    dirt = _leftovers(state)
    if dirt:
        return await _clean_after_reset(ctx, steps, dirt)
    where = "text area not found yet" if state.get("composer_len") == -1 else "empty composer, no attachment"
    steps.confirm("clean_start", where)
    return ""


def _needs(steps: JobSteps) -> tuple:
    """(image required, prompt required) — only what this job's stack actually did."""
    return "ATTACH_IMAGE" in steps.done_blocks, bool(_PROMPT_BLOCKS & steps.done_blocks)


def _composer_problem(state: dict, need_img: bool, need_prompt: bool) -> str:
    if need_img and not state.get("previews"):
        return "the image preview is not in the composer"
    if need_prompt and not state.get("prompt_ok"):
        return f"the text area does not hold the prompt ({state.get('composer_len')} chars)"
    return ""


async def _reinsert(ctx, steps: JobSteps, state: dict) -> dict:
    """The prompt went missing: type it once more and read again."""
    steps.warn("composer", "prompt not in the text area — inserting it again")
    try:
        await ctx.ctrl.insert_prompt(ctx.final_prompt)
    except Exception as exc:
        steps.warn("composer", f"re-insert failed: {exc}")
    await asyncio.sleep(0.3)
    return await read_state(ctx) or state


async def confirm_composer(ctx) -> bool:
    """Before the click: True = already sent (JOB-ID in the chat, do not click); raises when not ready."""
    steps = steps_of(ctx)
    need_img, need_prompt = _needs(steps)
    state = await _poll(ctx, lambda s: s.get("bubble") or not _composer_problem(s, need_img, need_prompt),
                        COMPOSER_TRIES)
    if not state:
        steps.warn("composer", "page not readable — image + prompt not confirmed, sending anyway")
        return False
    if state.get("bubble"):
        steps.confirm("composer", "the JOB-ID message is already in the chat — sent, not clicking again")
        return True
    _raise_page_error(steps, state, sent=False)
    if need_prompt and not state.get("prompt_ok"):
        state = await _reinsert(ctx, steps, state)
    problem = _composer_problem(state, need_img, need_prompt)
    if problem:
        raise RuntimeError(f"Composer check failed: {problem} — nothing sent, safe to retry")
    steps.confirm("composer", f"image preview {len(state.get('previews') or [])} + exact prompt in the text area")
    return False


def _sent_how(state: dict) -> str:
    if state.get("bubble"):
        return "JOB-ID message visible in the chat"
    if state.get("generating"):
        return "generation running"
    if state.get("composer_len") == 0:
        return "composer cleared"
    return ""


async def confirm_sent(ctx) -> str:
    """After the click: how the send showed ('' = uncertain, WAIT decides); raises when not delivered."""
    steps = steps_of(ctx)
    state = await _poll(ctx, _sent_how, SEND_TRIES)
    if not state:
        steps.warn("sent", "page not readable — the send is not confirmed; the wait decides")
        return ""
    _raise_page_error(steps, state, sent=True)
    how = _sent_how(state)
    if how:
        steps.confirm("sent", f"new job started ({how})")
        return how
    if state.get("prompt_ok") or state.get("marker_in_composer"):
        raise RuntimeError("Submit not delivered — the prompt is still in the composer (nothing sent, safe to retry)")
    steps.warn("sent", "no JOB-ID message yet and the composer changed — watching for the result")
    return ""


def confirm_saved(ctx, path, size: int) -> None:
    """The saved file exists and holds every byte; raises otherwise."""
    target = Path(path)
    try:
        on_disk = target.stat().st_size
    except OSError as exc:
        raise RuntimeError(f"Save not confirmed: {exc}") from exc
    if on_disk != size:
        raise RuntimeError(f"Save not confirmed: {on_disk}/{size} bytes on disk ({target.name})")
    steps_of(ctx).confirm("saved_on_disk", f"{target.name} · {size} bytes")
