# ideal-size: 90 lines reason=pool matching helpers for new-tab handover, share lock+endpoint logic
"""Pool matching — endpoint, owner, pattern counting for profile-correct handover."""

from __future__ import annotations

from typing import Any


def _get_pattern(bridge: Any) -> str:
    """URL pattern that decides which tabs suit pool (default arena.ai)."""
    try:
        cfg = getattr(bridge, "config", None)
        if cfg is not None:
            return str(cfg.get_state("url_pattern", "arena.ai") or "arena.ai")
    except Exception:
        pass
    return "arena.ai"


def _matches_pattern(url: str, pattern: str) -> bool:
    try:
        return pattern.lower() in (url or "").lower()
    except Exception:
        return False


def _endpoint_from_client(client: Any):
    """(host, port) from a CDP client, or None when missing."""
    try:
        h = getattr(client, "_host", None)
        p = getattr(client, "_port", None)
        if h and p:
            return str(h), int(p)
    except Exception:
        return None
    return None


def _endpoint_matches(client: Any, host: str, port: int) -> bool:
    """Client endpoint equals host:port."""
    ep = _endpoint_from_client(client)
    return ep is not None and ep[0] == host and ep[1] == port


def _owner_matches(page: Any, low: str) -> bool:
    """Page owner equals low (lowercased)."""
    try:
        return (getattr(page, "owner", "") or "").lower() == low
    except Exception:
        return False


def _count_profile_tabs(pool: Any, endpoint: tuple, pattern: str) -> int:
    """How many pooled tabs from same endpoint match pattern."""
    try:
        host, port = endpoint
        cnt = 0
        with pool._lock:
            for tid, page in pool._pages.items():
                try:
                    client, _ = pool.get_clients(tid)
                    if not _endpoint_matches(client, host, port):
                        continue
                    if _matches_pattern(getattr(page, "url", ""), pattern):
                        cnt += 1
                except Exception:
                    continue
        return cnt
    except Exception:
        return 0


def _count_profile_tabs_by_owner(pool: Any, endpoint: tuple, pattern: str, owner: str) -> int:  # quality-override: params=4 reason=profile needs host,port,pattern,owner tuple
    """Tabs on same endpoint matching pattern AND same owner."""
    if not owner:
        return 0
    try:
        host, port = endpoint
        low = owner.lower()
        cnt = 0
        with pool._lock:
            for tid, page in pool._pages.items():
                try:
                    if not _owner_matches(page, low):
                        continue
                    client, _ = pool.get_clients(tid)
                    if not _endpoint_matches(client, host, port):
                        continue
                    if _matches_pattern(getattr(page, "url", ""), pattern):
                        cnt += 1
                except Exception:
                    continue
        return cnt
    except Exception:
        return 0


def _pick_client_for_context(move: Any) -> Any:
    """First available client for Target.createTarget (profile-correct)."""
    for c in move.clients:
        if c is not None:
            return c
    return getattr(move.ctx, "client", None)
