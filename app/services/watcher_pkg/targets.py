"""Stable descriptions of pooled Watcher targets and legacy-controller fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WatcherTarget:
    """One pooled page the passive Watcher is allowed to inspect."""
    tab_id: str
    label: str
    cdp: Any


def normalize_targets(raw) -> list[WatcherTarget]:
    """Keep unavailable pool entries represented; absence is not an empty probe."""
    if not raw:
        return []
    if isinstance(raw, WatcherTarget):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [target for target in raw if isinstance(target, WatcherTarget)]
    tab_id = str(getattr(getattr(raw, "cdp", raw), "_current_tab_id", "") or "primary")
    return [WatcherTarget(tab_id, tab_id[:12], raw)]
