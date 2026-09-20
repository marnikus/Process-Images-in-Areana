"""Live debug read model (S6: the reconcile cadence; S9: the queue / cadence half of the
Live Worker & Queue Debug window).

`clamp_interval_ms` is the ONE clamp for `url_reconcile_interval_ms`
(`app_settings.apply_url_interval` and the JS control agree on it);
`interval_ms` reads it per call (the reconcile loop never caches);
`live_view` (= `cadence` + queued / next_image / receivers / run_state /
wait_reason) is what `layout_state.emit_arena_state` publishes as
`progress_updated.live` — read-only, no slot, no signal (D-20/D-22). The
workers half rides `page_pool_updated` unchanged; the JS merges the two.
Counts reuse S4's rule (`feed.eligible_images`) and S7's flag — never a
second rule.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Any, Iterable

from .feed import eligible_images

DEFAULT_MS, MIN_MS, MAX_MS = 5000, 500, 60000
KEY = "url_reconcile_interval_ms"


def clamp_interval_ms(value: Any) -> int:
    """500…60000 ms; garbage and None fall back to the default (never raise)."""
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MS
    return max(MIN_MS, min(MAX_MS, ms))


def interval_ms(bridge: Any) -> int:
    try:
        return clamp_interval_ms(bridge.config.get_state(KEY, DEFAULT_MS))
    except Exception:
        return DEFAULT_MS


def cadence(bridge: Any) -> dict:
    """`{url_interval_ms, last_pass_at, passes}` for the pushed progress payload."""
    from .reconcile import reconcile_state
    state = reconcile_state(bridge)
    return {"url_interval_ms": interval_ms(bridge), "last_pass_at": state.last_pass_at,
            "passes": state.passes}


def next_queued(images: Iterable) -> str:
    """The file name of the first image a pass would claim ("" when nothing is queued)."""
    queued = eligible_images(images)
    return os.path.basename(queued[0].relative_path or "") if queued else ""


def receiver_counts(rows: Iterable) -> dict:
    """How many URL rows can take a job now (S7's flag, counted — never recomputed)."""
    rows = list(rows)
    receivers = sum(1 for r in rows if getattr(r, "receiver", False))
    reasons = Counter(r.receiver_reason for r in rows if not getattr(r, "receiver", False) and r.receiver_reason)
    return {"total": len(rows), "receivers": receivers, "not_receivers": len(rows) - receivers,
            "reasons": dict(reasons)}


def live_view(bridge: Any) -> dict:
    """The pushed `progress_updated.live` payload: cadence + queue head + receivers + run/wait state."""
    from .supervisor import live_state
    images = getattr(bridge.state, "images", [])   # a state push must never die on a partial state (I-39)
    return {**cadence(bridge),
            "queued": len(eligible_images(images)), "next_image": next_queued(images),
            "receivers": receiver_counts(getattr(bridge.state, "urls", [])),
            "run_state": getattr(bridge, "_run_state", "idle"),
            "wait_reason": live_state(bridge).reason}
