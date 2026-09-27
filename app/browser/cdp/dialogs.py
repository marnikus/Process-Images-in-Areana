"""JavaScript dialogs that block the page — notice them, answer them (I-71).

Owner report (2026-09-27): after a manually solved captcha the image never
saved, the log said `🔍 Output check: no_result`, and the New Chat reset hung
at `FIND phase`. Every `Runtime.evaluate` on the tab — the job's and the
Watcher's — was timing out at 30 s.

Measured in Chrome (headless, puppeteer-core, 2026-09-27): while an
`alert()` / `confirm()` / `beforeunload` dialog is open, **no** evaluate is
answered, on any connection, until the dialog closes; Chrome says so with a
`Page.javascriptDialogOpening` event (the Page domain is enabled on every
connection, `connect._enable_cdp_domains`). Nothing listened for it, so an
unseen dialog (reCAPTCHA's own "Cannot contact reCAPTCHA" alert is one)
froze the whole job. Now every transport keeps a `DialogWatch`, and a probe
that meets a dialog answers it (`Page.handleJavaScriptDialog`) and goes on.

Answer policy: `alert` and `beforeunload` are accepted (an alert has no
choice; leaving the page is what our own navigation wants); `confirm` and
`prompt` are dismissed (never agree to something unknown). Each answer is
one warn line in the log.

ideal-size: ~130 lines — one responsibility (dialog state + answer); kept out of
transport.py so the transport stays under its 300-line cap.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

log = logging.getLogger("arena")

DIALOG_OPENING = "Page.javascriptDialogOpening"
DIALOG_CLOSED = "Page.javascriptDialogClosed"
ACCEPTED_KINDS = frozenset({"alert", "beforeunload"})
DIALOG_POLL_S = 0.5      # how often a waiting command looks for a new dialog
ANSWER_TIMEOUT_S = 5.0


def _log_warning(message: str) -> None:
    log.warning(message)


class DialogWatch:
    """The dialog open on this connection's page (events may arrive on the socket thread)."""

    def __init__(self, report: Callable[[str], None] = _log_warning):
        self.open: dict = {}
        self.report = report     # the bridge points this at the UI log

    def on_event(self, message: dict) -> None:
        method = message.get("method")
        if method == DIALOG_OPENING:
            self.open = describe(message.get("params") or {})
        elif method == DIALOG_CLOSED:
            self.open = {}


def report_to_log(client, log_fn: Callable[[str, str], None]):
    """Send this client's dialog notes to the UI log as warn lines; returns the client."""
    watch = getattr(client, "dialogs", None)
    if watch is not None:
        watch.report = lambda message: log_fn(message, "warn")
    return client


def describe(params: dict) -> dict:
    """The part of a dialog event worth telling: its kind and text."""
    return {"type": str(params.get("type") or "alert"),
            "message": str(params.get("message") or "")[:200]}


def should_accept(kind: str) -> bool:
    """Accept alerts and leave-page prompts; dismiss anything that asks a question."""
    return kind in ACCEPTED_KINDS


def dialog_text(dialog: dict) -> str:
    """"JavaScript alert 'Cannot contact reCAPTCHA…'" — what the owner reads."""
    return f"JavaScript {dialog.get('type', 'alert')} '{dialog.get('message', '')[:120]}'"


async def close_open_dialog(transport) -> str:
    """Answer the dialog blocking the page; the logged note ('' when none was open)."""
    watch = getattr(transport, "dialogs", None)
    dialog = dict(getattr(watch, "open", None) or {})
    if not dialog:
        return ""
    accept = should_accept(dialog["type"])
    watch.open = {}          # one answer per dialog: a stale entry must not re-fire forever
    failure = await _answer(transport, accept)
    if failure:
        return _tell(watch, f"💬 {dialog_text(dialog)} blocks the page and could not be closed ({failure})")
    verb = "accepted" if accept else "dismissed"
    return _tell(watch, f"💬 {dialog_text(dialog)} was blocking the page — {verb}, continuing")


async def _answer(transport, accept: bool) -> str:
    """Send the answer; why it failed ('' = done). Chrome's refusal is a reply, not a raise."""
    try:
        reply = await transport.send("Page.handleJavaScriptDialog", {"accept": accept},
                                     timeout=ANSWER_TIMEOUT_S)
    except Exception as exc:
        return str(exc) or type(exc).__name__
    error = reply.get("error") if isinstance(reply, dict) else None
    return str(error.get("message", error) if isinstance(error, dict) else error or "")


def _tell(watch, note: str) -> str:
    """One warn line through the watch's reporter (never raises)."""
    try:
        watch.report(note)
    except Exception:
        log.warning(note)
    return note


async def send_unblocked(transport, method: str, params: dict, timeout: float = 30.0) -> dict:
    """`send`, but a dialog that opens while we wait is answered so the reply can come."""
    task = asyncio.ensure_future(transport.send(method, params, timeout=timeout))
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=DIALOG_POLL_S)
            if done:
                return task.result()
            await close_open_dialog(transport)
    except asyncio.CancelledError:
        task.cancel()                                      # the command frees its own waiter
        await asyncio.gather(task, return_exceptions=True)
        raise
