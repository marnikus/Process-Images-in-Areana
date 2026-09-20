# ideal-size: ~45 lines reason=S6 budget — interval + cadence for the debug window; grows to ~90 in S9 (RULE 18.2)
"""live/debug_view (S6) — interval setting and cadence payload (I-42).

The reconciler's cadence is a user setting (500–60000 ms, default 5000)
stored in `config/session.json` via `ConfigManager`. One clamp owner
(`clamp_interval_ms`) and one reader (`interval_ms`); the JS control
writes through `save_settings` and reads through `progress_updated.live`.
"""

from __future__ import annotations


def clamp_interval_ms(value) -> int:
    """User interval, clamped 500–60000, default 5000 on garbage."""
    try: iv = int(value) if value is not None else 5000
    except Exception: return 5000
    return 500 if iv < 500 else 60000 if iv > 60000 else iv


def interval_ms(bridge) -> int:
    """Current interval for the reconciler (reads every pass, S6)."""
    try:
        raw = bridge.config.get_state("url_reconcile_interval_ms", 5000)
        return clamp_interval_ms(raw)
    except Exception:
        return 5000


def cadence(bridge) -> dict:
    """Payload for `progress_updated.live` (S6: interval + last pass)."""
    try:
        from app.services.live.reconcile import last_pass_at
        last = last_pass_at(bridge)
    except Exception:
        last = float(getattr(bridge, "_last_reconcile_at", 0) or 0)
    passes = int(getattr(bridge, "_reconcile_passes", 0) or 0)
    return {"url_interval_ms": interval_ms(bridge), "last_pass_at": last, "passes": passes}
