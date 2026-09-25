"""Firefox worker names + the visual tab id overlay — WHEN to identify (2026-09-25).

Identity vs display (design: docs/archive/2026-09-25-firefox-account-name/):
the pool key `{profileDir}_tab{N}` IS the worker. The account name, the
profile name and the visual number are display metadata this module refreshes
and never uses as a key — a failed detection cannot create, drop or rename a
worker; the label simply stays on its fallback rung (`FirefoxPageInfo.alias`).

`observe(bridge, tabs, manual)` runs at the end of every reconcile pass (the
`LiveDeps.identify` seam) and never awaits a macro, so discovery is never
blocked. It marks pages due on: first sight, navigation (the session URL
changed), reconnect, a manual Reparse, or a number/name that no longer matches
the overlay last aimed at. One background drain then runs the identify macro
per due page (`firefox_lane.run_identify` — the jobs' machine-wide lock). A
failed attempt retries after 15 / 45 / 120 s, then rests until the next
trigger. A tab that left the pool while still open gets one clear run, so no
stale overlay survives reconciliation.

Imports: services (`firefox_lane`, `tab_owner`, `run_state`) + the browser
identify module for the reply format. No ui.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.browser.uivision import identify as uv_identify
from app.services.firefox_lane import run_identify
from app.services.live.tab_owner import store_owner
from app.services.run_state import schedule_coro

log = logging.getLogger("arena")

RETRY_DELAYS = (15.0, 45.0, 120.0)   # bounded: 3 retries, then rest until a trigger
LEASE_SEC = 600.0                     # a drain that died unseen frees the slot after this
_now = time.monotonic                 # test seam


@dataclass
class Track:
    """What the drain knows about one pooled Firefox tab (display state only)."""

    url: str = ""
    connected: bool = True
    aimed: str = ""                  # overlay text of the last attempt (`2# name`)
    attempts: int = 0                # failures in the current trigger cycle
    due_at: Optional[float] = 0.0    # monotonic stamp; None = resting
    reason: str = "first sight"


@dataclass
class Book:
    """Per-bridge identify state: tracks by pool key, pending clears, the drain lease."""

    tracks: Dict[str, Track] = field(default_factory=dict)
    clears: Dict[str, Any] = field(default_factory=dict)   # key → live row (left the pool)
    busy_until: float = 0.0


def book_of(bridge) -> Book:
    book = getattr(bridge, "_ff_identity", None)
    if not isinstance(book, Book):
        book = Book()
        bridge._ff_identity = book
    return book


def overlay_text(page) -> str:
    """The overlay a page should show — `<visual number># <display name>`."""
    return f"{int(page.worker_no or 0)}# {page.label}"


def observe(bridge, tabs, manual: bool = False) -> bool:
    """Mark due pages + queue clears; start the drain when needed (True = started)."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return False
    book, live = book_of(bridge), _live_rows(tabs)
    pages = _firefox_pages(pool)
    for tab_id, page in pages.items():
        _observe_page(book, (tab_id, page), live.get(tab_id), manual)
    _forget_departed(book, pages, live)
    if not _work_waiting(book, pages) or _now() < book.busy_until:
        return False
    book.busy_until = _now() + LEASE_SEC
    schedule_coro(bridge, drain(bridge))
    return True


def _live_rows(tabs) -> dict:
    """Firefox rows of this pass by pool key (rows carrying a profile directory)."""
    return {t.id: t for t in tabs or () if hasattr(t, "profile_dir") and getattr(t, "id", "")}


def _firefox_pages(pool) -> dict:
    with pool._lock:
        return {k: p for k, p in pool._pages.items() if getattr(p, "browser", "") == "firefox"}


def _observe_page(book: Book, entry, row, manual: bool) -> None:
    tab_id, page = entry
    track = book.tracks.get(tab_id)
    if track is None:
        book.tracks[tab_id] = track = Track(url=page.url, connected=page.is_connected)
    book.clears.pop(tab_id, None)            # back in the pool: the redraw replaces it
    reason = _trigger(track, page, row, manual)
    if row is not None:
        page.url, page.title = row.url or page.url, row.title or page.title
    if reason:
        track.due_at, track.attempts, track.reason = 0.0, 0, reason
    track.url, track.connected = page.url, page.is_connected


def _trigger(track: Track, page, row, manual: bool) -> str:
    """Why this page must be identified again ('' = nothing changed)."""
    if row is not None and row.url and row.url != track.url:
        return "navigation"
    if page.is_connected and not track.connected:
        return "reconnect"
    if manual:
        return "manual refresh"
    if track.aimed and overlay_text(page) != track.aimed:
        return "label change"
    return ""


def _forget_departed(book: Book, pages: dict, live: dict) -> None:
    """A key that left the pool loses its track; an open tab gets one clear run."""
    for tab_id in [k for k in book.tracks if k not in pages]:
        track = book.tracks.pop(tab_id)
        if track.aimed and tab_id in live:
            book.clears[tab_id] = live[tab_id]


def _work_waiting(book: Book, pages: dict) -> bool:
    return bool(book.clears) or any(_ready(book, k, p) for k, p in pages.items())


def _ready(book: Book, tab_id: str, page) -> bool:
    track = book.tracks.get(tab_id)
    due = track is not None and track.due_at is not None and track.due_at <= _now()
    return due and page.is_connected and not page.is_busy()


async def drain(bridge) -> int:
    """Run every due identify / clear, one macro at a time; returns how many ran."""
    book, done = book_of(bridge), 0
    try:
        while True:
            book.busy_until = _now() + LEASE_SEC
            if not await _run_next(bridge, book):
                return done
            done += 1
    finally:
        book.busy_until = 0.0


async def _run_next(bridge, book: Book) -> bool:
    if book.clears:
        tab_id, row = book.clears.popitem()
        kind, message, _reply = await _attempt(bridge, row, uv_identify.payload(0, "", clear=True))
        log.debug("identify: stale overlay clear on %s — %s %s", tab_id, kind, message)
        return True
    pool = getattr(bridge, "_page_pool", None)
    pages = _firefox_pages(pool) if pool is not None else {}
    tab_id = next((k for k, p in pages.items() if _ready(book, k, p)), None)
    if tab_id is None:
        return False
    await _identify(bridge, book, (tab_id, pages[tab_id]))
    return True


async def _attempt(bridge, page, cmd_payload: str) -> tuple:
    """One identify macro → (kind, safe message, parsed reply); a crash is an answer."""
    try:
        kind, message, lines = await run_identify(bridge, page, cmd_payload)
    except Exception as exc:  # cancel still propagates (BaseException)
        log.warning("identify crashed on %s", getattr(page, "tab_id", "?"), exc_info=True)
        kind, message, lines = "error", f"identify crashed: {type(exc).__name__}", ()
    return kind, _safe(message), uv_identify.parse_reply(lines)


async def _identify(bridge, book: Book, entry) -> None:
    tab_id, page = entry
    track = book.tracks[tab_id]
    track.aimed, track.due_at = overlay_text(page), None
    kind, message, reply = await _attempt(
        bridge, page, uv_identify.payload(page.worker_no, page.label))
    page.name_checked_at = time.time()
    track.aimed = reply.get("text") or track.aimed
    if reply.get("email"):
        _detected(bridge, entry, reply["email"])
        track.attempts = 0
    else:
        stage = "element" if kind == "ok" else "macro"
        why = (f"account element not found within {uv_identify.WAIT_MS} ms"
               if kind == "ok" else f"{kind}: {message}")
        _failed(bridge, entry, track, (stage, why))
    _emit(bridge)


def _detected(bridge, entry, email: str) -> None:
    tab_id, page = entry
    fresh = email != page.owner or page.name_source != "detected"
    store_owner(bridge._page_pool, tab_id, page, email)
    page.name_source = "detected"
    if fresh:
        bridge._log(f"🦊 Account detected — worker {tab_id} · profile “{_profile(page)}” "
                    f"→ {overlay_text(page)}", "success")


def _failed(bridge, entry, track: Track, cause: tuple) -> None:
    """Concise warning (worker, profile, stage, safe reason) + the bounded retry."""
    tab_id, page = entry
    stage, why = cause
    track.attempts += 1
    if track.attempts <= len(RETRY_DELAYS):
        delay = RETRY_DELAYS[track.attempts - 1]
        track.due_at = _now() + delay
        tail = f"retry {track.attempts}/{len(RETRY_DELAYS)} in {int(delay)}s"
    else:
        tail = "no more retries until navigation, reconnect or Reparse"
    bridge._log(f"🦊⚠ Account name not detected — worker {tab_id} · profile "
                f"“{_profile(page)}” · stage {stage} ({track.reason}) · {why} — "
                f"showing “{page.label}”; {tail}", "warn")


def _profile(page) -> str:
    return getattr(page, "profile", "") or "unnamed"


_TAG_RE = re.compile(r"<[^>]*>?")


def _safe(message: Any) -> str:
    """One short line: markup stripped, whitespace collapsed, clipped (never a page dump)."""
    return " ".join(_TAG_RE.sub(" ", str(message or "")).split())[:120]


def _emit(bridge) -> None:
    try:
        bridge._emit_pool_status()
    except Exception as exc:  # display refresh only
        log.debug("identify: pool emit skipped: %s", exc)
