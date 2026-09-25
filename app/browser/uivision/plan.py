"""From sessions to runs — which profile, which tab, which selector (pure).

The multi-profile planner: `plan_targets` turns per-profile session rows into one
`Target` per matching tab (every profile, every matching tab — never just the
freshest), and `runs_by_profile` renders ONE `PlannedRun` per profile (2026-09-24
lifecycle redesign): each run addresses its profile's FIRST match, because
`firefox -P <name> <url>` is ignored when Firefox already runs (the remote command
line hands the URL to the already-running instance) — one launch per TAB stormed
the first instance with N autostart tabs while the other profiles never ran.

Selector priority (the report's rule, adapted to what `selectWindow` offers — the
official docs list only `title=` and relative `tab=N`, there is no `url=`): a set
title pattern becomes the user's literal `title=*{pattern}*` (the extension matches
LIVE titles, fresh by construction); anything else resolves at LAUNCH time to a
relative `tab=N` from a fresh session-store read (tab positions outlive dynamic
page titles — building title globs from the store was the E212 source). Title text
is never constructed from detection output. Imports only `paths` and `launch` from
this package; no OS calls, no asyncio.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import launch, paths

TITLE_CLIP = 40


@dataclass(frozen=True)
class Search:
    """The two tab filters as one value — blank means ANY on either side."""

    pattern: str = ""       # tab-title substring (the window's TAB TITLE PATTERN)
    url_pattern: str = ""   # tab-URL substring (the window's TAB URL PATTERN)


@dataclass(frozen=True)
class Target:
    """One macro run's destination: a matching tab inside ONE profile instance."""

    profile_name: str = ""    # the profiles.ini name ('' = no `-P` handle known)
    profile_dir: str = ""     # the profile directory (the `-profile` fallback)
    url: str = ""
    title: str = ""
    windows: tuple = ()       # this profile's session windows (the foreground map)
    window_index: int = -1    # 0-based session window holding the tab (-1 = rows had no map)
    tab_pos: int = -1         # 0-based position of the tab inside its window (-1 = unknown)


@dataclass(frozen=True)
class PlannedRun:
    """One macro run with every value rendered — the runner executes these in order."""

    target: Target
    index: int            # 1-based position in the sequence
    total: int
    label: str            # `profile “X” · tab “Y”` for the report lines
    selector: str         # the title literal, or "" = resolve a tab=N at launch
    profile_args: tuple   # ("-P", name) / ("-profile", dir) / () — cold starts only
    log_path: str         # this run's own savelog (run 1 keeps the plain name)
    search: Search = Search()   # the filters that matched (the resolver reads them)
    tabs: tuple = ()      # EVERY match in this profile (target is the first)


def profile_label(name: str, profile_dir: str = "") -> str:
    """The display name: the profiles.ini name, else the directory's basename."""
    text = (name or "").strip()
    if text:
        return text
    return Path(profile_dir).name if (profile_dir or "").strip() else ""


def anonymous_session(rows) -> dict:
    """Flat tab rows as one unnamed profile — the faked `tabs` seam's shape."""
    return {"name": "", "dir": "", "rows": list(rows or []), "windows": [],
            "source": "", "stamp": -1.0}


ANY_TAB = "any tab"


def matches(title, url, pattern, url_pattern) -> bool:
    """(title, url) against two optional substrings — a blank pattern means any.

    The owner's rule (2026-09-24): empty title pattern = any title, empty URL
    pattern = any URL; a tab must satisfy BOTH filters to run.
    """
    want_title = (pattern or "").strip().lower()
    want_url = (url_pattern or "").strip().lower()
    if want_title and want_title not in (title or "").lower():
        return False
    return not want_url or want_url in (url or "").lower()


def describe_search(pattern, url_pattern) -> str:
    """The active filters in one readable phrase (`any tab` when both are blank)."""
    title = (pattern or "").strip()
    url = (url_pattern or "").strip()
    if not title and not url:
        return ANY_TAB
    left = f'title “{title}”' if title else "any title"
    right = f'URL “{url}”' if url else "any URL"
    return f"{left} + {right}"


def _targets_from_windows(session, pattern: str, url_pattern: str) -> list:
    """One Target per matching tab, window positions recorded (the mapped shape)."""
    name = str(session.get("name", ""))
    profile_dir = str(session.get("dir", ""))
    windows = tuple(session.get("windows") or ())
    targets = []
    for pos, window in enumerate(windows):
        for tab_no, tab in enumerate((window or {}).get("tabs") or []):
            title, url = str(tab.get("title", "")), str(tab.get("url", ""))
            if url and matches(title, url, pattern, url_pattern):
                targets.append(Target(profile_name=name, profile_dir=profile_dir,
                                      url=url, title=title, windows=windows,
                                      window_index=pos, tab_pos=tab_no))
    return targets


def _targets_from_rows(session, pattern: str, url_pattern: str) -> list:
    """One Target per matching flat row — the windowless (anonymous-seam) shape."""
    name = str(session.get("name", ""))
    profile_dir = str(session.get("dir", ""))
    targets = []
    for row in session.get("rows") or []:
        title, url = str(row.get("title", "")), str(row.get("url", ""))
        if matches(title, url, pattern, url_pattern):
            targets.append(Target(profile_name=name, profile_dir=profile_dir,
                                  url=url, title=title, windows=()))
    return targets


def plan_targets(sessions, pattern: str, url_pattern: str = "") -> list:
    """One Target per tab matching BOTH patterns — every profile, stable order.

    A blank pattern matches any (owner rule, 2026-09-24): blank title + blank
    URL plan a run for every open tab. Matching runs over each session's WINDOWS
    (so every target knows its window + position for the tab=N resolver) and
    falls back to the flat `rows` when a session carries no window map.
    """
    targets = []
    for session in sessions or []:
        if session.get("windows"):
            targets.extend(_targets_from_windows(session, pattern, url_pattern))
        else:
            targets.extend(_targets_from_rows(session, pattern, url_pattern))
    return targets


def selector_for(pattern: str) -> str:
    """The plan-time selector: the user's title literal, or "" for launch resolve.

    A set title pattern is used VERBATIM (`title=*{pattern}*`) — never rebuilt
    from detection output. A blank one answers "" so the sequence resolves a
    fresh relative `tab=N` at launch (`resolve_selector`).
    """
    want = (pattern or "").strip()
    return f"title=*{want}*" if want else ""


def _relative_index(tab_pos: int, tab_count: int) -> str:
    """`tab=N` relative to the autostart tab (`pos - count`, always ≤ -1).

    Ui.Vision counts selectWindow tabs RELATIVE to the macro's start tab
    (tab=0 IS the start tab, -1 one tab left of it): the Ctrl+T invocation
    tab always appends LAST (0-based index = count), so a target at 0-based
    `pos` among `count` tabs answers `pos - count` (single tab → tab=-1).
    """
    return f"tab={tab_pos - tab_count}"


def _first_url_match(window, url_pattern: str):
    """(tab_pos, tab_count) of the window's first URL-matching tab (None if none)."""
    tabs = list((window or {}).get("tabs") or [])
    want = (url_pattern or "").strip().lower()
    for pos, tab in enumerate(tabs):
        if not want or want in str(tab.get("url", "")).lower():
            return pos, len(tabs)
    return None


def resolve_selector(run: PlannedRun, sessions) -> tuple | None:
    """(selector, [window]) against FRESH sessions — None when unresolvable.

    Title-pattern runs answer the plan-time literal plus the plan-time window
    holding the target URL (`plan_window`); index runs search the run's profile
    for the first URL match and answer its relative `tab=N` plus that window.
    Delivery maps into exactly the answered window, so aiming and delivery can
    never disagree about which window holds the tab.
    """
    if (run.search.pattern or "").strip():
        return run.selector, plan_window(list(run.target.windows), run.target.url)
    return _resolve_index(run, sessions or [])


def _resolve_index(run: PlannedRun, sessions: list):
    """The fresh relative tab=N inside the run's own profile (None when gone)."""
    for session in sessions:
        if str(session.get("dir", "")) != run.target.profile_dir:
            continue
        for window in session.get("windows") or []:
            found = _first_url_match(window, run.search.url_pattern)
            if found is not None:
                pos, count = found
                return _relative_index(pos, count), [window]
    return None


def plan_window(windows, url: str) -> list:
    """[the first window holding `url`] — the title run's delivery map ([] if none)."""
    for window in windows or []:
        if any(str(tab.get("url", "")) == (url or "") for tab in (window or {}).get("tabs") or []):
            return [window]
    return list(windows or [])


def run_label(target: Target) -> str:
    """`profile “X” · tab “Y”` for the report lines (`tab “Y”` alone when unnamed)."""
    who = profile_label(target.profile_name, target.profile_dir)
    tab = (target.title or target.url or "?")[:TITLE_CLIP]
    return f'profile “{who}” · tab “{tab}”' if who else f'tab “{tab}”'


def multi_matches(targets) -> list:
    """[(profile label, count, first title)] for profiles with 2+ matches.

    One run addresses one profile's FIRST match — every crowded profile is
    named so the owner can narrow the pattern for the rest (RULE 4).
    """
    counts: dict = {}
    for target in targets or []:
        label = profile_label(target.profile_name, target.profile_dir) or "?"
        counts.setdefault(label, []).append(target)
    return [(label, len(rows), (rows[0].title or rows[0].url or "?")[:TITLE_CLIP])
            for label, rows in counts.items() if len(rows) > 1]


def summarize(targets, real: bool) -> str:
    """The run plan in one line: one run per profile, matches grouped per profile."""
    groups = _group_by_profile(targets)
    if not real:
        return (f"{len(groups)} macro run(s) — one Firefox instance "
                f"(no profile selection)")
    counts: dict = {}
    for target in targets or []:
        label = profile_label(target.profile_name, target.profile_dir) or "?"
        counts[label] = counts.get(label, 0) + 1
    parts = ", ".join(f"“{label}” ×{count}" for label, count in counts.items())
    return f"{len(groups)} macro run(s) — {parts}"


def _group_by_profile(targets) -> list:
    """[profile targets...] grouped by profile dir, first-seen order (stable)."""
    groups: dict = {}
    for target in targets or []:
        groups.setdefault(str(target.profile_dir or ""), []).append(target)
    return list(groups.values())


def run_scope(run) -> str:
    """`run i/n (label): ` for multi-run lines ("" when the run stands alone)."""
    return f"run {run.index}/{run.total} ({run.label}): " if run.total > 1 else ""


def runs_by_profile(targets, search: Search, config_dir, stamp: str) -> list:
    """One PlannedRun per profile: the first match runs, its own savelog each."""
    groups = _group_by_profile(targets)
    total = len(groups)
    planned = []
    for index, rows in enumerate(groups, 1):
        first = rows[0]
        planned.append(PlannedRun(
            target=first, index=index, total=total, label=run_label(first),
            selector=selector_for(search.pattern),
            profile_args=launch.profile_args(first.profile_name, first.profile_dir),
            log_path=str(paths.log_file(config_dir, stamp, part=index if index > 1 else 0)),
            search=search, tabs=tuple(rows)))
    return planned