"""Read-only views of the live loops for the UI (S6: the URL reconcile cadence).

One clamp owner for the reconcile interval (`clamp_interval_ms`): the setting
slot and the JS control both mirror these bounds; the loop reads
`interval_ms` every pass, so a saved value applies without a restart.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.live.url_policy import receiver_title

INTERVAL_KEY = "url_reconcile_interval_ms"
MIN_MS = 500
MAX_MS = 60000
DEFAULT_MS = 5000


def clamp_interval_ms(value: Any) -> int:
    """`MIN_MS…MAX_MS`; garbage (None, text) becomes the default, never raises."""
    try:
        ms = int(value if value not in (None, "") else DEFAULT_MS)
    except (TypeError, ValueError):
        ms = DEFAULT_MS
    return max(MIN_MS, min(ms, MAX_MS))


def interval_ms(bridge) -> int:
    """The configured reconcile interval (clamped on read too — a hand-edited file stays safe)."""
    try:
        return clamp_interval_ms(bridge.config.get_state(INTERVAL_KEY, DEFAULT_MS))
    except Exception:
        return DEFAULT_MS


def cadence(bridge) -> Dict[str, Any]:
    """`{url_interval_ms, last_pass_at, passes}` — rides on `progress_updated`."""
    stats = getattr(bridge, "_reconcile_stats", None) or {}
    return {"url_interval_ms": interval_ms(bridge),
            "last_pass_at": float(stats.get("last_pass_at", 0.0)),
            "passes": int(stats.get("passes", 0))}


def annotate_receivers(bridge, js_urls: List[Dict[str, Any]]) -> None:
    """Add `receiver_title` (the ⊘ tooltip) to pushed rows — same predicate as the flag, read at emit."""
    pool = getattr(bridge, "_page_pool", None)
    rows = {u.id: u for u in getattr(bridge.state, "urls", None) or []}
    for js_row in js_urls:
        row = rows.get(js_row.get("id"))
        js_row["receiver_title"] = receiver_title(row, pool) if row is not None else ""
