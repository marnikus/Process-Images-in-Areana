# ideal-size: read-only projection leaf; queue eligibility stays in core and pool data stays on its own signal.
"""Live queue projection and reconcile cadence; services import core, never UI.

The reconciler's cadence is a user setting (500–60000 ms, default 5000)
stored in `config/session.json` via `ConfigManager`. One clamp owner
(`clamp_interval_ms`) and one reader (`interval_ms`); the JS control
writes through `save_settings` and reads through `progress_updated.live`.
"""

from __future__ import annotations

from .feed import eligible_images


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


def next_queued(images) -> str:
    """First eligible filename in queue order; never sort or invent a rule."""
    pending = eligible_images(images)
    return pending[0].filename if pending else ""


def receiver_counts(rows) -> dict:
    """Report the authoritative flag without recalculating eligibility."""
    receiving = sum(bool(row.receiver) for row in rows)
    return {"total": len(rows), "receivers": receiving,
            "not_receivers": len(rows) - receiving}


def live_view(bridge) -> dict:
    """Read-only queue/cadence payload, independent of the pool snapshot."""
    images = list(bridge.state.images)
    rows = list(bridge.state.urls)
    return {**cadence(bridge), "queued": len(eligible_images(images)),
            "next_image": next_queued(images), "receivers": receiver_counts(rows),
            "run_state": str(getattr(bridge, "_run_state", "idle"))}
