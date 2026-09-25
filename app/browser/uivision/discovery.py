"""Stable-identity Firefox tab discovery — session files only, no debugger.

Every open profile's session store (`tabs.profile_sessions` + the lock probe
in `profiles.open_sessions`) answers one `FirefoxTab` per tab, carrying the
TabInfo shape the merged reconcile fetch expects (`id`, `title`, `url`,
`ws_url=""` — Ui.Vision never has a socket) plus what execution needs:
the profile dir/name and that profile's session windows (the foreground map).

Identity (design D-2, owner's §2.2): `tab_id = "{profileDirBase}_tab{n}"`
with `n` the tab's 0-based index in the profile's flattened session order —
the same store order every rescan, so the same tab gets the same id every
time. `is_tab_id` recognises that shape: CDP target ids are hex and never end
`_tab<digits>`, which is how one pass tells the two browsers' keys apart.

Everything is best-effort: a refused or unparsable profile contributes no
rows, never an error (RULE 4). Pure functions take `sessions`/`in_use`
seams so tests never read a real machine's Firefox.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from app.core.browser_ids import FIREFOX, TAB_ID_RE, is_tab_id  # noqa: F401  (re-exported seam)

from . import profiles, tabs


@dataclass(frozen=True)
class FirefoxTab:
    """One open tab, shaped like `cdp.tabs.TabInfo` for the merged fetch (D-1)."""

    id: str
    url: str = ""
    title: str = ""
    ws_url: str = ""          # never a socket — the Ui.Vision lane has none
    type: str = "page"
    browser: str = FIREFOX
    profile_dir: str = ""
    profile_name: str = ""    # profiles.ini `Name=` ('' = address by directory)
    tab_index: int = 0        # 0-based flattened index — the stable half of the id
    windows: tuple = ()       # this profile's session windows (foreground mapping)


def tab_id_for(profile_dir: str, index: int) -> str:
    """The stable pool key of one tab (owner's §2.2 format)."""
    return f"{Path(profile_dir or '').name}_tab{int(index)}"


def tab_index_of(tab_id: str) -> int:
    """The tab's 0-based session index, or -1 when the key is not ours."""
    match = TAB_ID_RE.match(tab_id or "")
    return int(match.group("index")) if match else -1


def _session_tabs(session: dict) -> list:
    """Every tab of one session as `FirefoxTab` (flattened index = the id's n)."""
    profile_dir = str(session.get("dir") or "")
    if not profile_dir:
        return []
    windows = tuple(session.get("windows") or ())
    out = []
    for index, row in enumerate(session.get("rows") or []):
        out.append(FirefoxTab(
            id=tab_id_for(profile_dir, index),
            url=str(row.get("url") or ""),
            title=str(row.get("title") or ""),
            profile_dir=profile_dir,
            profile_name=str(session.get("name") or ""),
            tab_index=index,
            windows=windows,
        ))
    return out


def discover(selected: Iterable = (), *, sessions=None, in_use=None) -> list:
    """Open profiles' tabs, restricted to `selected` dirs when named ([] = all).

    `sessions` replaces the real session-store read and `in_use` the lock
    probe (tests inject both); the real path reads every profile and keeps
    only the RUNNING ones (2026-09-24 bug #4 rule — freshness is no liveness).
    """
    rows = tabs.profile_sessions() if sessions is None else list(sessions)
    wanted = profiles.selected_set(selected)
    out = []
    for session in profiles.open_sessions(rows, in_use):
        if wanted and str(session.get("dir") or "") not in wanted:
            continue
        out.extend(_session_tabs(session))
    return out


def find_target(tab_id: str, selected: Iterable = (), *, sessions=None,
                in_use=None) -> Optional[FirefoxTab]:
    """The one live tab with this pool id — None when it is closed or filtered.

    The execution lane's honest answer (RULE 4): a pool entry whose tab the
    user closed resolves to None and the job fails by name, never a launch at
    a different tab.
    """
    return next((tab for tab in discover(selected, sessions=sessions, in_use=in_use)
                 if tab.id == tab_id), None)
