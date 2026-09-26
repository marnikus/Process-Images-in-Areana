"""Firefox image job — the bridge seams the job AND its recovery call (audit R3, 2026-09-26).

One home for what both sides need from the app: a log line, a state save, the
config folder, the settings and the Chrome lane's timeout knobs. Every seam
catches — a broken UI / persist callback never kills the pipeline — and a
failure is never silent: it reaches the `arena` logger as a warning (RULE 5).

Layer: a leaf. No Qt, no lane, no job types — `firefox_job_journal`,
`firefox_job_ctx` and `firefox_job_recovery` all import it, never the reverse.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("arena")

_HERE = Path(".")


def call(what: str, action: Callable[[], Any]) -> bool:
    """Run one bridge callback; a failure is a logged warning, never raised."""
    try:
        action()
        return True
    except Exception as exc:  # RULE 5: the pipeline outlives any UI callback
        logger.warning("Firefox job: %s failed: %s", what, exc)
        return False


def say(bridge, text: str, level: str = "info") -> None:
    """One line in the app log (RULE 2)."""
    call("log line", lambda: bridge._log(text, level))


def persist(bridge) -> None:
    """Progress recount + the app state save (the Chrome lane's pair)."""
    def _save() -> None:
        bridge.state.recalculate_progress()
        bridge._save_arena()
    call("state save", _save)


def config_dir(bridge, fallback: Optional[Path] = _HERE) -> Optional[Path]:
    """The app's config folder, or `fallback` when the bridge has no real one."""
    directory = getattr(getattr(bridge, "config", None), "dir", None)
    return Path(directory) if isinstance(directory, (str, Path)) else fallback


def settings_of(bridge):
    """`bridge.state.settings`, or None on a bare bridge."""
    return getattr(getattr(bridge, "state", None), "settings", None)


def timeout_s(bridge, key: str, default: int) -> int:
    """`settings.timeouts[key]` — the same knobs the Chrome lane reads."""
    try:
        return int(settings_of(bridge).timeouts.get(key, default))
    except (AttributeError, TypeError, ValueError):
        return default
