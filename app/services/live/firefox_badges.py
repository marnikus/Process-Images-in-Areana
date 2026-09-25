"""Firefox visual tab ID overlay — centered top badge (2026-09-25).

Mirrors Chrome's ``worker_badges`` service but for Firefox pool entries that
have no CDP client. The JS lives in ``browser.worker_badge`` (``FIREFOX_ATTR``)
and shows ``<worker_no># <account>`` per spec, reusing Chrome's CSS constants
so visual style matches. Idempotent: re-running removes the previous overlay,
never duplicates, and ``pointer-events:none`` never blocks controls.

Direct ``client.evaluate`` is tried first (tests inject a fake client); when
absent the macro fallback (``firefox_helpers.build_firefox_overlay_macro``)
would be the reliable path — the service accepts an injected ``evaluate``
callable so tests and the reconcile seam stay deterministic.

Stale overlays are replaced on every pass; a disconnected tab's overlay is
cleared on the captured client before removal (same order as Chrome badge).
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Tuple

from app.browser.worker_badge import (
    FirefoxBadgeSpec,
    build_firefox_badge_clear_js,
    build_firefox_badge_js,
)

log = logging.getLogger(__name__)


def _firefox_display_name(page, pool) -> str:
    """Firefox display fallback — same chain as page_pool (email → profile → id)."""
    try:
        from app.browser.page_pool import _firefox_display_name as pool_name

        return pool_name(page, pool)
    except Exception:
        return str(getattr(page, "tab_id", "") or "")[:12]


def firefox_pages(pool: Any) -> Iterable[Tuple[str, Any]]:
    """Yield ``(tab_id, page)`` for every connected Firefox entry."""
    try:
        pages = dict(getattr(pool, "_pages", None) or {})  # type: ignore[attr-defined]
    except Exception:
        return []
    for tab_id, page in pages.items():
        try:
            if (getattr(page, "browser", "") or "").strip().lower() != "firefox":
                continue
            if not getattr(page, "is_connected", False):
                continue
            yield tab_id, page
        except Exception:
            continue


def _client_of(pool: Any, tab_id: str):
    try:
        return pool.get_clients(tab_id)[0]  # type: ignore[union-attr]
    except Exception:
        return None


async def _evaluate_quietly(client: Any, js: str, tab_id: str) -> bool:
    try:
        await client.evaluate(js)  # type: ignore[union-attr]
        return True
    except Exception as exc:  # cosmetic
        log.debug("firefox badge skipped for %s: %s", str(tab_id)[:12], exc)
        return False


def _firefox_spec(page, pool, tab_id: str) -> FirefoxBadgeSpec:
    display = _firefox_display_name(page, pool)
    return FirefoxBadgeSpec(
        worker_no=int(getattr(page, "worker_no", 0) or 0),
        account=display,
        tab_id=tab_id,
        profile=display,
    )


async def _try_evaluate(evaluate, tab_id: str, js: str) -> bool:
    if not callable(evaluate):
        return False
    try:
        await evaluate(tab_id, js)  # type: ignore[arg-type]
        return True
    except Exception as exc:
        log.debug("firefox macro evaluate refused for %s: %s", tab_id[:12], exc)
        return False


async def assert_firefox_badges(pool: Any, evaluate=None, bridge: Any = None) -> int:
    """Show ``N# account`` on every connected Firefox page; returns count shown."""
    if pool is None:
        return 0
    shown = 0
    for tab_id, page in firefox_pages(pool):
        spec = _firefox_spec(page, pool, tab_id)
        js = build_firefox_badge_js(spec)
        if await _try_evaluate(evaluate, tab_id, js):
            shown += 1
            continue
        client = _client_of(pool, tab_id)
        if client is not None and await _evaluate_quietly(client, js, tab_id):
            shown += 1
    return shown


async def clear_firefox_badge(client: Any, tab_id: str) -> bool:
    """Remove the Firefox overlay via a captured client; False when absent."""
    if client is None:
        return False
    return await _evaluate_quietly(client, build_firefox_badge_clear_js(), tab_id)


async def clear_all_firefox_badges(pool: Any, evaluate=None) -> int:
    """Remove Firefox overlays from every Firefox page that has a client."""
    if pool is None:
        return 0
    cleared = 0
    for tab_id, _ in firefox_pages(pool):
        if callable(evaluate):
            try:
                await evaluate(tab_id, build_firefox_badge_clear_js())
                cleared += 1
                continue
            except Exception:
                pass
        client = _client_of(pool, tab_id)
        if await clear_firefox_badge(client, tab_id):
            cleared += 1
    return cleared
