"""Discovery: the checked, open Firefox profiles' matching tabs (I-64, 2026-09-25).

One pass handles every checked profile dir that is OPEN (`tabs.profile_in_use`):
- read its session doc (decoded only when the file changed — `DocCache`);
- walk the windows, keeping each tab's real strip position;
- keep tabs with a URL that match the Firefox window's patterns (`plan.matches`);
- give each one a stable id from the `FoxTabBook`.

A profile whose session cannot be read keeps its last tabs for this pass
(a failed read is a wait, never a close). The scanner is shared by the
reconcile pass and the job planner (both run in executor threads), so every
entry point holds one lock. No Qt, no bridge.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.core.tab_alias import CONN_UIVISION, FIREFOX

from .. import mozlz4, tabs
from ..plan import Patterns, matches, profile_label
from .identity import FoxTabBook


@dataclass(frozen=True)
class FoxTab:
    """One Firefox tab as the pool sees it — duck-types the CDP `TabInfo` fields reconcile reads."""

    id: str
    url: str
    title: str
    profile_dir: str
    profile_name: str = ""
    window: int = 1          # 1-based window number in the session store
    index: int = 0           # 0-based strip position inside its window
    ws_url: str = ""         # no socket: a Firefox tab joins by id
    browser: str = FIREFOX
    conn: str = CONN_UIVISION
    type: str = "page"

    @property
    def profile_label(self) -> str:
        return profile_label(self.profile_name, self.profile_dir)


@dataclass
class ScanSeams:
    """The OS boundaries (tests fake them); None = the real reader."""

    in_use: Optional[Callable] = None     # profile dir → bool (open?)
    names: Optional[Callable] = None      # () → {profile dir: profiles.ini name}
    doc: Optional[Callable] = None        # profile dir → (doc, stamp, source)


@dataclass
class ScanResult:
    tabs: List[FoxTab] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)   # named reasons (kept tabs, unreadable)


@dataclass(frozen=True)
class Located:
    """One tab after a fresh read: itself, its profile's windows, its OS-map window row."""

    tab: FoxTab
    windows: tuple        # positioned windows (the locator's input)
    window_row: dict      # `tabs.window_rows` entry of its window (the foreground map)


class DocCache:
    """Session docs decoded once per file change (mtime + size), shared across passes."""

    def __init__(self, read: Optional[Callable] = None) -> None:
        self._read = read or mozlz4.read_session_file
        self._docs: Dict[str, tuple] = {}

    def __call__(self, path):
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        key = (stat.st_mtime_ns, stat.st_size)
        hit = self._docs.get(str(path))
        if hit is not None and hit[0] == key:
            return hit[1]
        doc = self._read(path)
        self._docs[str(path)] = (key, doc)
        return doc


def _dicts(value) -> list:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def positioned_windows(doc) -> list:
    """[[{"url","title"}]] per window — EVERY tab kept, so list index = strip index."""
    out = []
    for window in _dicts((doc or {}).get("windows")):
        row = []
        for tab in _dicts(window.get("tabs")):
            entry = tabs.current_entry(tab)
            row.append({"url": str(entry.get("url") or ""), "title": str(entry.get("title") or "")})
        out.append(row)
    return out


def matching_slots(windows: list, patterns: Patterns) -> list:
    """(window no, index, flat, url, title) of every tab with a URL that matches the patterns."""
    slots, flat = [], 0
    for window_no, row in enumerate(windows, 1):
        for index, tab in enumerate(row):
            flat += 1
            if tab["url"] and matches(tab["title"], tab["url"], patterns):
                slots.append((window_no, index, flat, tab["url"], tab["title"]))
    return slots


class FoxScanner:
    """Discovery state across passes: the id book, the doc cache, each profile's last answer."""

    def __init__(self, book: Optional[FoxTabBook] = None, seams: Optional[ScanSeams] = None) -> None:
        self.book = book or FoxTabBook()
        self.seams = seams or ScanSeams()
        self._cache = DocCache()
        self._lock = threading.Lock()
        self._last: Dict[str, List[FoxTab]] = {}
        self._windows: Dict[str, tuple] = {}

    def scan(self, profiles: list, patterns: Patterns) -> ScanResult:
        """One pass over the checked profiles that are open (none checked → nothing)."""
        with self._lock:
            names = self._names()
            result = ScanResult()
            for profile in self._open(profiles):
                found, note = self._profile_tabs(profile, names.get(profile, ""), patterns)
                result.tabs.extend(found)
                result.notes.extend([note] if note else [])
            return result

    def locate(self, profile: str, tab_id: str, patterns: Patterns) -> Optional[Located]:
        """One id after a FRESH read of its profile; None when the tab is gone."""
        with self._lock:
            found, _note = self._profile_tabs(profile, self._names().get(profile, ""), patterns)
            tab = next((t for t in found if t.id == tab_id), None)
            if tab is None:
                return None
            windows, maps = self._windows.get(profile, ((), ()))
            row = maps[tab.window - 1] if 0 < tab.window <= len(maps) else {}
            return Located(tab=tab, windows=tuple(windows), window_row=row)

    def last_tab(self, tab_id: str) -> Optional[FoxTab]:
        """The tab as the last pass saw it (None when no pass listed it)."""
        with self._lock:
            return next((t for found in self._last.values() for t in found if t.id == tab_id), None)

    def _names(self) -> dict:
        return (self.seams.names or tabs.profile_names)()

    def _open(self, profiles: list) -> list:
        probe = self.seams.in_use or tabs.profile_in_use
        return [p for p in dict.fromkeys(str(x) for x in profiles or []) if p.strip() and probe(p)]

    def _read(self, profile: str) -> tuple:
        if self.seams.doc is not None:
            return self.seams.doc(profile)
        return tabs.session_doc(profile, read=self._cache)

    def _profile_tabs(self, profile: str, name: str, patterns: Patterns) -> tuple:
        """This profile's matching tabs + a note; an unreadable store keeps the last answer."""
        doc, _stamp, _source = self._read(profile)
        if not isinstance(doc, dict):
            kept = list(self._last.get(profile, []))
            label = profile_label(name, profile)
            return kept, f"{label}: no readable session store yet — kept {len(kept)} tab(s)"
        windows = positioned_windows(doc)
        slots = matching_slots(windows, patterns)
        ids = self.book.assign(Path(profile).name, [(s[3], s[2]) for s in slots])
        found = [FoxTab(id=tid, url=s[3], title=s[4], profile_dir=profile, profile_name=name,
                        window=s[0], index=s[1]) for tid, s in zip(ids, slots)]
        self._last[profile] = found
        self._windows[profile] = (tuple(windows), tuple(tabs.window_rows(doc)))
        return found, ""
