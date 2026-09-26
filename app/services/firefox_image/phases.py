"""One image-job phase at a time (I-65).

Each function is one verified step. Submit is called only when the book does
not already say the send was launched. Pause waits; it does not redo a
verified phase.

Imports: sibling steps/checkpoint/save/log only.
"""

from __future__ import annotations

import base64
from pathlib import Path

from app.core.enums import ImageStatus

from . import checkpoint, log, save, steps


def say(env, name: str, detail: str = "") -> None:
    """One phase line on this job's correlation id."""
    log.phase(env.job.bridge, env.corr_id, name, detail)


def offer_bytes(data: dict) -> bytes:
    """Bytes from a download echo (`raw` in tests, base64 from the macro)."""
    raw = data.get("raw") if isinstance(data, dict) else None
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    try:
        return base64.b64decode(data.get("b64") or "")
    except Exception:
        return b""


async def act(env, phase: str, payload: dict) -> dict:
    """One transport call. A non-dict answer is a named failure (RULE 4)."""
    reply = await env.transport.act(phase, payload)
    if isinstance(reply, dict):
        return reply
    return {"kind": "error", "message": "empty macro reply", "data": {}}


async def probe(env) -> dict:
    """Current page snapshot. A failed probe is an empty page, not a crash."""
    reply = await act(env, "probe", {})
    data = reply.get("data") or {}
    return data if isinstance(data, dict) else {}


def _marked(preview: dict, baseline) -> dict:
    """Stamp `fresh` when this preview src was not on the page before upload."""
    marked = dict(preview or {})
    src = str(marked.get("src") or "")
    marked["fresh"] = bool(src) and src not in set(baseline or ())
    return marked


def _snap(reply: dict) -> dict:
    """The upload/prompt echo is the snapshot when it carries page fields."""
    data = reply.get("data") or {}
    if isinstance(data, dict) and ("attachment" in data or "prompt" in data or "results" in data):
        return data
    return {}


def _remember_baseline(book: dict, snap: dict) -> None:
    """Srcs already on the page — a later result must not be one of these."""
    results = snap.get("results") or []
    book["baseline"] = [c.get("src") for c in results if c.get("src")]


async def _confirm_upload(env, book: dict, expected: str, reply: dict) -> bool:
    """The upload echo (or a fresh probe) must show this file's preview."""
    seen = _snap(reply) or await probe(env)
    preview = _marked(seen.get("attachment") or {}, book.get("baseline") or [])
    problem = steps.attachment_problem(preview, expected)
    if problem:
        return _upload_failed(env, problem)
    say(env, "Attached", expected)
    return _verified(env, book, preview.get("name") or expected)


async def _upload_new(env, book: dict, expected: str) -> bool:
    """Open the file dialog and require the preview that comes back."""
    say(env, "Attach started", env.job.img.absolute_path)
    reply = await act(env, "upload", {"path": env.job.img.absolute_path})
    if reply.get("kind") != "ok":
        return _upload_failed(env, reply.get("message") or "upload failed")
    return await _confirm_upload(env, book, expected, reply)


async def attach(env, book: dict) -> bool:
    """Clear a stale preview, upload, and require a matching preview."""
    expected = Path(env.job.img.absolute_path).name
    snap = await probe(env)
    _remember_baseline(book, snap)
    if not await _drop_stale(env, snap, expected):
        return False
    if _already_attached(snap, book, expected):
        return _verified(env, book, expected)
    return await _upload_new(env, book, expected)


async def _drop_stale(env, snap: dict, expected: str) -> bool:
    """Remove a previous job's preview. Still present → fail, do not upload."""
    preview = snap.get("attachment") or {}
    if not steps.stale_attachment(preview, expected):
        return True
    say(env, "Attach started", "clearing stale attachment")
    await act(env, "clear", {})
    again = await probe(env)
    if (again.get("attachment") or {}).get("found"):
        return _upload_failed(env, "stale attachment from previous job")
    snap.clear()
    snap.update(again)
    return True


def _already_attached(snap: dict, book: dict, expected: str) -> bool:
    preview = _marked(snap.get("attachment") or {}, book.get("baseline") or [])
    return not steps.attachment_problem(preview, expected)


def _verified(env, book: dict, detail: str) -> bool:
    say(env, "Attachment verified", detail)
    book["phase"] = "attachment_verified"
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    return True


def _upload_failed(env, reason: str) -> bool:
    say(env, "Attach failed", reason)
    env.job.img.status = ImageStatus.FAILED.value
    env.job.img.error = reason
    return False


async def insert_prompt(env, book: dict) -> bool:
    """Insert and require an exact read-back (multiline and Unicode included)."""
    say(env, "Inserted", f"len {len(env.prompt)}")
    reply = await act(env, "prompt", {"prompt": env.prompt})
    actual = str((reply.get("data") or {}).get("actual") or "")
    if not actual:
        actual = str((await probe(env)).get("prompt") or "")
    problem = steps.prompt_problem(actual, env.prompt)
    if problem or reply.get("kind") != "ok":
        reason = problem or reply.get("message") or "prompt failed"
        say(env, "prompt failed", reason)
        env.job.img.status = ImageStatus.FAILED.value
        env.job.img.error = reason
        return False
    say(env, "Verified", "exact match")
    book["phase"] = "prompt_verified"
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    return True


async def submit_once(env, book: dict) -> bool:
    """Persist intent, then click Send once. A lost ack is not a second click."""
    say(env, "Submit intent", "send will fire once")
    book["submitted"] = True
    book["phase"] = "submit_intent"
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    reply = await act(env, "submit", {})
    if reply.get("kind") == "ok":
        book["phase"] = "submitted"
        book["submit_uncertain"] = False
        say(env, "Clicked send", "send clicked once")
    else:
        book["phase"] = "submit_uncertain"
        book["submit_uncertain"] = True
        say(env, "Submit acknowledgment lost", reply.get("message") or reply.get("kind") or "lost ack")
    checkpoint.save_book(env.job.bridge, env.job.img.id, book)
    return True
