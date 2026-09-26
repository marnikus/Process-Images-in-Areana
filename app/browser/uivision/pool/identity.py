"""Stable Firefox tab ids across rescans — `{profileDirName}_tab{N}` (pure, I-64).

The session store offers no tab id that survives a restart, so the book
re-matches every scan of one profile against what it saw before, in order:

1. same URL at the same flat position (unchanged),
2. same URL at the nearest old position (the tab moved),
3. same flat position with a new URL (the tab navigated),
4. otherwise a new id: `_tab{N}`, N = the smallest free number ≥ its position.

An id that goes unmatched survives `GRACE_SCANS` scans, so a session-store
hiccup never renumbers a tab. `seed` loads persisted URL rows (id + URL), so
ids survive app restarts too. No I/O, no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from app.core.tab_alias import firefox_tab_id, split_firefox_id

GRACE_SCANS = 3

Scanned = Tuple[str, int]          # (url, 1-based flat position in the profile)


@dataclass
class Seen:
    """What the book remembers about one id: its last URL, position and misses."""

    url: str
    flat: int
    misses: int = 0


def _same_url_same_pos(free: Dict[str, Seen], url: str, flat: int) -> Optional[str]:
    return next((tid for tid, seen in free.items() if seen.url == url and seen.flat == flat), None)


def _same_url_nearest(free: Dict[str, Seen], url: str, flat: int) -> Optional[str]:
    hits = [(abs(seen.flat - flat), tid) for tid, seen in free.items() if seen.url == url]
    return min(hits)[1] if hits else None


def _same_pos(free: Dict[str, Seen], url: str, flat: int) -> Optional[str]:
    return next((tid for tid, seen in free.items() if seen.flat == flat), None)


RULES = (_same_url_same_pos, _same_url_nearest, _same_pos)


def match_known(known: Dict[str, Seen], tabs: List[Scanned]) -> List[Optional[str]]:
    """Known ids for the scanned tabs, rule by rule over ALL tabs (None = new tab).

    A rule runs for every tab before the next rule starts, so a moved tab keeps
    its own id (rule 2) before a navigated neighbour can claim its position (rule 3).
    """
    ids: List[Optional[str]] = [None] * len(tabs)
    free = dict(known)
    for rule in RULES:
        for pos, (url, flat) in enumerate(tabs):
            if ids[pos] is not None:
                continue
            hit = rule(free, url, flat)
            if hit is not None:
                ids[pos] = hit
                free.pop(hit)
    return ids


def number_new(dir_name: str, taken: set, flat: int) -> str:
    """A fresh id: `_tab{flat}` when free, else the next free number above it."""
    number = max(1, int(flat))
    while firefox_tab_id(dir_name, number) in taken:
        number += 1
    return firefox_tab_id(dir_name, number)


def _age(known: Dict[str, Seen], matched: set) -> None:
    """Unmatched ids count a miss; past the grace they are forgotten."""
    for tab_id in [tid for tid in known if tid not in matched]:
        known[tab_id].misses += 1
        if known[tab_id].misses > GRACE_SCANS:
            del known[tab_id]


class FoxTabBook:
    """Every profile's known ids (by profile dir name) — the one owner of Firefox tab ids."""

    def __init__(self) -> None:
        self._profiles: Dict[str, Dict[str, Seen]] = {}

    def seed(self, pairs: Iterable[Tuple[str, str]]) -> int:
        """Remember persisted (tab id, url) pairs; returns how many ids were new."""
        added = 0
        for tab_id, url in pairs or []:
            name, number = split_firefox_id(tab_id)
            known = self._profiles.setdefault(name, {}) if number else None
            if known is None or tab_id in known:
                continue
            known[tab_id] = Seen(url=str(url or ""), flat=number)
            added += 1
        return added

    def assign(self, dir_name: str, tabs: List[Scanned]) -> List[str]:
        """One profile's scan → one id per tab (scan order); the book learns the answer."""
        known = self._profiles.setdefault(dir_name, {})
        ids = match_known(known, tabs)
        taken = set(known) | {tid for tid in ids if tid}
        for pos, (url, flat) in enumerate(tabs):
            if ids[pos] is None:
                ids[pos] = number_new(dir_name, taken, flat)
                taken.add(ids[pos])
            known[ids[pos]] = Seen(url=url, flat=flat)
        _age(known, set(ids))
        return list(ids)

    def known_ids(self, dir_name: str) -> List[str]:
        """The ids the book holds for one profile (tests and the log read it)."""
        return sorted(self._profiles.get(dir_name, {}))
