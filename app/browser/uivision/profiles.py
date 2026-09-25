"""Profile listing and selection — the Firefox-auto window's profile filter.

Pure functions (no Qt, no bridge, no OS calls beyond the session-store reads
already owned by `tabs.py`): `list_profiles` turns the session store into the
window's display rows — OPEN profiles only (a profile is "open" while its
`lock.ini` pid is alive; the on-screen finder must show what Firefox is
running right now, not every saved profile — owner rule 2026-09-24),
`selected_set` normalises the config's list into a lookup, and
`filter_targets` keeps only targets whose profile is selected. A blank
selection means *every* profile (no filter) — the empty-list default.
"""

from __future__ import annotations

from pathlib import Path

from . import tabs
from .plan import Target, profile_label

TAB_CAP = 8  # tabs shown per profile in the UI row; a long list is truncated


def _profile_id(session: dict) -> str:
    """The stable identifier one config stores — the profile dir (always set)."""
    return str(session.get("dir") or "")


def _tab_summary(rows: list) -> tuple:
    """(shown, total) — the profile's tab count plus the capped URL list."""
    urls = [row.get("url", "") for row in (rows or [])[:TAB_CAP]]
    return urls, len(rows or [])


def list_profiles() -> list:
    """Every Firefox profile that is RUNNING now, as a display row.

    Open-only (owner rule 2026-09-24: the finder shows what Firefox is running
    right now, not every saved profile) — a profile whose `lock.ini` pid is
    dead carries a stale store and is not listed. Each row: `{"id", "name",
    "dir", "tabs", "tab_count", "source"}`; the `id` is the profile dir (the
    stable key); `name` is the `profiles.ini` handle (`""` when unnamed). An
    empty list means no profile is running.
    """
    out = []
    for session in tabs.open_profile_sessions():
        shown, total = _tab_summary(session.get("rows"))
        out.append({
            "id": _profile_id(session),
            "name": str(session.get("name") or ""),
            "dir": _profile_id(session),
            "tabs": shown,
            "tab_count": total,
            "source": str(session.get("source") or ""),
        })
    return out


def selected_set(selected: list) -> set:
    """The selected profile dirs as a lookup set — blank means *every* profile."""
    ids = {str(item).strip() for item in (selected or []) if str(item).strip()}
    return ids


def _target_id(target: Target) -> str:
    """The target's profile key — the dir matches the config's stored id."""
    return str(target.profile_dir or "")


def filter_targets(targets: list, selected: list) -> list:
    """Keep only targets whose profile dir is in `selected` (all when blank)."""
    ids = selected_set(selected)
    if not ids:
        return list(targets or [])
    return [t for t in (targets or []) if _target_id(t) in ids]


def unmatched_profiles(sessions: list, targets: list, selected: list) -> list:
    """Selected profiles with zero matching tabs — the skip-or-wait answer.

    Only selected profiles appear (a deselected one was already skipped by
    `filter_targets`); a blank selection reports every unanswered profile.
    """
    ids = selected_set(selected)
    hit_dirs = {_target_id(t) for t in (targets or [])}
    out = []
    for session in sessions or []:
        pid = _profile_id(session)
        if ids and pid not in ids:
            continue
        if pid not in hit_dirs:
            out.append(profile_label(session.get("name", ""), pid))
    return out
