"""URL reconcile cadence — the single clamp owner and the progress payload shape (S6)."""
from __future__ import annotations

CONFIG_KEY = "url_reconcile_interval_ms"
MIN_INTERVAL_MS = 500
MAX_INTERVAL_MS = 60000
DEFAULT_INTERVAL_MS = 5000


def clamp_interval_ms(value) -> int:
    """Garbage → the default; otherwise 500..60000 (the only clamp owner)."""
    try:
        ms = int(value)
    except (TypeError, ValueError):
        ms = DEFAULT_INTERVAL_MS
    return max(MIN_INTERVAL_MS, min(ms, MAX_INTERVAL_MS))


def interval_ms(bridge) -> int:
    """The configured cadence, read on call — never cached by the loop."""
    cfg = getattr(bridge, "config", None)
    getter = getattr(cfg, "get_state", None)
    if getter is None:
        return DEFAULT_INTERVAL_MS
    return int(getter(CONFIG_KEY, DEFAULT_INTERVAL_MS))


def cadence(bridge) -> dict:
    """The `live` section of progress_updated (the interval control's read path)."""
    return {"url_interval_ms": interval_ms(bridge),
            "last_pass_at": float(getattr(bridge, "_last_url_pass", 0.0)),
            "passes": int(getattr(bridge, "_url_pass_count", 0))}
