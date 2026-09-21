"""S6: live debug values — the reconcile interval, clamped and published."""

INTERVAL_DEFAULT_MS = 5000
INTERVAL_MIN_MS = 500
INTERVAL_MAX_MS = 60000


def clamp_interval_ms(value):
    """User input -> [500, 60000]; garbage falls back to 5000."""
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return INTERVAL_DEFAULT_MS
    return max(INTERVAL_MIN_MS, min(INTERVAL_MAX_MS, ms))


def interval_ms(bridge):
    """The loop's current cadence, read fresh every pass (default when unreadable)."""
    get = getattr(getattr(bridge, "config", None), "get_state", None)
    raw = get("url_reconcile_interval_ms") if callable(get) else None
    return clamp_interval_ms(raw)


def cadence(bridge):
    """The live block published in progress_updated."""
    return {"url_interval_ms": interval_ms(bridge),
            "last_pass_at": getattr(bridge, "_reconcile_last_pass_at", 0.0),
            "passes": getattr(bridge, "_reconcile_passes", 0)}
