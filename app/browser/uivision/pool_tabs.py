"""Firefox tabs as pool citizens — stable ids, the listing, the join (2026-09-25).

Read-only eyes over every OPEN profile's session store (`tabs.profile_sessions`
filtered by the lock probe in `profiles.open_sessions` — closed profiles never
answer). Each tab gets the id `{profile-dir-basename}_tab{N}` (N = 1-based flat
session order), which is deterministic from the session file and therefore
STABLE across rescans — the owner's §2.2 contract. The row object carries the
attributes `auto_connect` already reads (`.id` / `.url` / `.title` /
`.ws_url`), where the ws_url is the join sentinel `firefox://{id}` — the
planner, the removal table and the presence sync never learn about browsers
(design D1). Pattern filtering stays the planner's job (RULE 10).

Imports: sibling uivision modules + `page_status` only — no services, no ui.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..page_status import PageInfo
from . import profiles, tabs

FIREFOX_SCHEME = "firefox://"
BROWSER = "firefox"


@dataclass
class FirefoxTab:
    """One open Firefox tab in planner shape — id, url, title, profile, sentinel."""

    id: str
    url: str
    title: str
    profile: str       # profiles.ini name ('' = unnamed)
    profile_dir: str   # the profile directory (identity's source + `-profile` arg)
    ws_url: str = ""   # `firefox://{id}` — what `plan.connect` carries


@dataclass
class FirefoxPageInfo(PageInfo):
    """A pool entry that is a Firefox tab — profile attribution rides the entry.

    Subclass (not extra fields on `PageInfo`): the base class sits on its
    zero-tolerance class-LOC ratchet (design D3).
    """

    browser: str = BROWSER
    profile: str = ""
    profile_dir: str = ""

    def to_dict(self) -> dict:
        wire = super().to_dict()
        wire["profile"] = self.profile
        wire["profile_dir"] = self.profile_dir
        return wire


def tab_id_for(profile_dir, index: int) -> str:
    """`{profile-dir-basename}_tab{N}` — stable across rescans (owner §2.2)."""
    return f"{Path(str(profile_dir)).name}_tab{int(index)}"


def ws_for(tab_id: str) -> str:
    return f"{FIREFOX_SCHEME}{tab_id}"


def is_firefox_ws(ws) -> bool:
    return isinstance(ws, str) and ws.startswith(FIREFOX_SCHEME)


def tab_id_from_ws(ws) -> str:
    return ws[len(FIREFOX_SCHEME):] if is_firefox_ws(ws) else ""


def firefox_rows(profiles_filter=None, in_use=None) -> list:
    """Every open tab of every checked profile (`None`/`()` = every profile).

    One row per flat session entry — matching and miss-hysteresis are the
    reconciler's job, never this listing's (D1).
    """
    sessions = tabs.profile_sessions(profiles_filter)
    out = []
    for session in profiles.open_sessions(sessions, in_use):
        directory = str(session.get("dir") or "")
        for index, row in enumerate(session.get("rows") or [], 1):
            url = str(row.get("url") or "")
            tab_id = tab_id_for(directory, index)
            out.append(FirefoxTab(id=tab_id, url=url,
                                  title=str(row.get("title") or ""),
                                  profile=str(session.get("name") or ""),
                                  profile_dir=directory, ws_url=ws_for(tab_id)))
    return out


def find_tab(tab_id: str, profiles_filter=None, in_use=None):
    """The live session row for this id (None when the tab is no longer open)."""
    return next((t for t in firefox_rows(profiles_filter, in_use) if t.id == tab_id), None)


def page_for(tab: FirefoxTab) -> FirefoxPageInfo:
    """The pool entry for a discovered tab — ready to `pool.add_page`."""
    return FirefoxPageInfo(ws_url="", tab_id=tab.id, url=tab.url, title=tab.title,
                           browser=BROWSER, is_connected=True,
                           profile=tab.profile, profile_dir=tab.profile_dir)
