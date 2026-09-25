"""Firefox account name resolver — display-metadata only (2026-09-25).

Runs for every Firefox pool entry that is connected. Tries the Ui.Vision macro
probe (``firefox_helpers.build_firefox_account_probe_js``) via an injected
``evaluate`` callable (tests) or falls back to a bridge's macro runner when
available. On failure the worker's identity never changes (RULE 15) and the
fallback chain is kept: detected → last-known (AliasBook) → profile → short id.

Never logs page HTML, credentials, tokens or cookies — only worker id, profile,
stage and a safe reason. Retries with bounded delay (loading page) but never
blocks worker discovery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.browser.uivision.firefox_helpers import (
    build_firefox_account_probe_js,
    interpret_firefox_account,
)
from app.core.tab_alias import normalize_owner

log = logging.getLogger(__name__)

_RETRY_DELAYS = (0.4, 1.2)  # bounded retry when page still loading
_MAX_RETRY = len(_RETRY_DELAYS)


def _profile_of(page) -> str:
    try:
        prof = (getattr(page, "profile", "") or "").strip()
        if prof:
            return prof
        pdir = (getattr(page, "profile_dir", "") or "").strip()
        if pdir:
            from pathlib import Path

            return Path(pdir).name.strip()
    except Exception:
        pass
    return ""


def _label_for_log(pool, tab_id: str) -> str:
    try:
        from app.browser.page_pool import tab_label_of

        return tab_label_of(pool, tab_id)
    except Exception:
        return tab_id[:12]


async def _evaluate_probe(client: Any, js: str) -> str:
    """One evaluate call → raw string (empty on refusal)."""
    try:
        result = await client.evaluate(js)  # type: ignore[attr-defined]
        if result is None:
            return ""
        return str(result)
    except Exception as exc:  # cosmetic never raises
        log.debug("firefox probe evaluate refused: %s", exc)
        return ""


async def _read_owner_via_evaluate(page, pool, evaluate) -> str:
    """Probe via injected evaluate callable or pool client if present.

    ``evaluate`` is ``async (tab_id, js) -> raw`` (tests) or we fallback to
    ``pool.get_clients(tab_id)[0].evaluate`` when a Firefox client exists.
    """
    js = build_firefox_account_probe_js()
    raw = ""
    if callable(evaluate):
        try:
            raw = await evaluate(getattr(page, "tab_id", ""), js)  # type: ignore[arg-type]
        except Exception as exc:
            log.debug("firefox evaluate callable failed: %s", exc)
            raw = ""
    else:
        try:
            client, _ = pool.get_clients(getattr(page, "tab_id", ""))  # type: ignore[union-attr]
            if client is not None:
                raw = await _evaluate_probe(client, js)
        except Exception:
            raw = ""
    return normalize_owner(interpret_firefox_account(raw).get("email"))


def _store_owner(pool, page, email: str) -> None:
    try:
        with pool._lock:  # type: ignore[attr-defined]
            page.owner = email  # type: ignore[attr-defined]
            book = getattr(pool, "_alias", None)
            if book is not None:
                book.remember(getattr(page, "tab_id", ""), email)
            # cache for lifecycle (timestamp + source)
            page._firefox_display_source = "detected"  # type: ignore[attr-defined]
            page._firefox_display_seen = time.time()  # type: ignore[attr-defined]
    except Exception:
        pass


def _warn_detection_failed(page, stage: str, reason: str, pool=None) -> None:
    try:
        label = _label_for_log(pool if hasattr(pool, "_pages") else None, getattr(page, "tab_id", ""))
        profile = _profile_of(page) or "unknown"
        safe = (reason or "probe returned no email")[:120].replace("\n", " ")
        msg = (
            f"⚠ Firefox account detection failed worker {label} "
            f"profile {profile} stage {stage} — {safe} — using fallback"
        )
        tried = False
        if pool is not None:
            # bridge has _log, pool has _logger — try both
            for attr in ("_log", "_logger"):
                try:
                    fn = getattr(pool, attr, None)
                    if callable(fn):
                        fn(msg, "warn")  # type: ignore[misc]
                        tried = True
                        break
                except Exception:
                    continue
        if not tried:
            log.warning(msg)
    except Exception:
        pass


def _is_loading_title(page) -> bool:
    try:
        title = (getattr(page, "title", "") or "").strip().lower()
        return "loading" in title or "new tab" in title or not title
    except Exception:
        return False


def _collect_firefox_targets(pool) -> list:
    try:
        pages = dict(getattr(pool, "_pages", None) or {})  # type: ignore[attr-defined]
    except Exception:
        return []
    out = []
    for tab_id, page in pages.items():
        try:
            browser = (getattr(page, "browser", "") or "").strip().lower()
            if browser != "firefox":
                continue
            if not getattr(page, "is_connected", False):
                continue
            out.append((tab_id, page))
        except Exception:
            continue
    return out


async def _probe_with_retry(page, pool, evaluate, retry_delays) -> tuple:
    email = await _read_owner_via_evaluate(page, pool, evaluate)
    attempts = 0
    while not email and attempts < len(retry_delays):
        if not _is_loading_title(page) and attempts > 0:
            break
        await asyncio.sleep(retry_delays[attempts])
        email = await _read_owner_via_evaluate(page, pool, evaluate)
        attempts += 1
    return email, attempts


async def _resolve_one(page, pool, evaluate, retry_delays=_RETRY_DELAYS) -> tuple:
    email, attempts = await _probe_with_retry(page, pool, evaluate, retry_delays)
    if not email:
        return False, attempts
    if email != getattr(page, "owner", ""):
        _store_owner(pool, page, email)
    return True, attempts


async def resolve_firefox_owners(
    pool: Any,
    bridge: Any = None,
    evaluate=None,
    retry_delays: tuple = _RETRY_DELAYS,
) -> int:
    """Probe every connected Firefox page; returns how many accounts were read."""
    if pool is None:
        return 0
    targets = _collect_firefox_targets(pool)
    found = 0
    for _tab_id, page in targets:
        ok, attempts = await _resolve_one(page, pool, evaluate, retry_delays)
        if ok:
            found += 1
        else:
            reason = "empty probe" if attempts == 0 else f"empty after {attempts} retries"
            target = bridge if bridge is not None and hasattr(bridge, "_log") else pool
            _warn_detection_failed(page, "initial_scan", reason, target)
    return found


# Convenience wrapper for reconcile/join seams that lack a bridge.
async def resolve_firefox_owners_for_pool(pool: Any, evaluate=None) -> int:
    return await resolve_firefox_owners(pool, bridge=None, evaluate=evaluate)
