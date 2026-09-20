"""Live debug read model (S6: the reconcile cadence; S9 adds the worker/queue view).

`clamp_interval_ms` is the ONE clamp for `url_reconcile_interval_ms`
(`app_settings.apply_url_interval` and the JS control agree on it);
`interval_ms` reads it per call (the reconcile loop never caches);
`cadence` is what `layout_state.emit_arena_state` publishes as
`progress_updated.live` — the control's only read path (D-12R, D-20).
"""

from __future__ import annotations

from typing import Any

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
