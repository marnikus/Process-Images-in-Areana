"""From sessions to runs — which profile, which tab, which selector (pure).

The multi-profile planner: `plan_targets` turns per-profile session rows into one
`Target` per matching tab (every profile, every matching tab — never just the
freshest), and `runs` renders each target into a `PlannedRun` the runner executes:
its own `selectWindow` selector (the tab's own title glob, so the second matching
tab is not skipped for the first), its own profile argv prefix (`-P name`, or
`-profile dir` when no `profiles.ini` name exists — Firefox hands the URL to THAT
profile's running instance) and its own savelog file. Imports only `paths` and
`launch` from this package; no OS calls, no asyncio.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import launch, paths

TITLE_CLIP = 40


@dataclass(frozen=True)
class Target:
    """One macro run's destination: a matching tab inside ONE profile instance."""

    profile_name: str = ""    # the profiles.ini name ('' = no `-P` handle known)
    profile_dir: str = ""     # the profile directory (the `-profile` fallback)
    url: str = ""
    title: str = ""
    windows: tuple = ()       # this profile's session windows (the foreground map)


@dataclass(frozen=True)
class PlannedRun:
    """One macro run with every value rendered — the runner executes these in order."""

    target: Target
    index: int            # 1-based position in the sequence
    total: int
    label: str            # `profile “X” · tab “Y”` for the report lines
    selector: str         # cmd_var3 — the selectWindow target
    profile_args: tuple   # ("-P", name) / ("-profile", dir) / () — rides before the URL
    log_path: str         # this run's own savelog (run 1 keeps the plain name)


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


def selector_for(target: Target, pattern: str) -> str:
    """The selectWindow target: this tab's own title glob, else the pattern glob."""
    title = (target.title or "").strip()
    if title:
        return f"title=*{title}*"
    want = (pattern or "").strip()
    return f"title=*{want}*" if want else ""


def run_label(target: Target) -> str:
    """`profile “X” · tab “Y”` for the report lines (`tab “Y”` alone when unnamed)."""
    who = profile_label(target.profile_name, target.profile_dir)
    tab = (target.title or target.url or "?")[:TITLE_CLIP]
    return f'profile “{who}” · tab “{tab}”' if who else f'tab “{tab}”'


def _session_identifiers(session: dict) -> tuple:
    name = (session.get("name") or "").strip().lower()
    p_dir = (session.get("dir") or "").strip().lower()
    base = Path(p_dir).name.lower() if p_dir else ""
    return name, p_dir, base


def profile_matches(session: dict, selected: list) -> bool:
    """True when session matches any selector in selected (or selected is empty)."""
    if not selected:
        return True
    identifiers = set(_session_identifiers(session)) - {""}
    chosen = {str(s or "").strip().lower() for s in selected} - {""}
    return bool(identifiers & chosen)


def filter_sessions(sessions: list, selected_profiles: list) -> list:
    """Keep only sessions whose name, dir, or dir basename is in selected_profiles."""
    if not selected_profiles:
        return list(sessions or [])
    return [s for s in (sessions or []) if profile_matches(s, selected_profiles)]


def plan_targets(sessions, pattern: str, url_pattern: str = "") -> list:
    """One Target per tab matching BOTH patterns — every profile, stable order.

    A blank pattern matches any (owner rule, 2026-09-24): blank title + blank
    URL plan a run for every open tab. Matching runs over each session's flat
    `rows`; `windows` only decorates the Target for the foreground mapping.
    """
    targets = []
    for session in sessions or []:
        windows = tuple(session.get("windows") or ())
        for row in session.get("rows") or []:
            if matches(str(row.get("title", "")), str(row.get("url", "")),
                       pattern, url_pattern):
                targets.append(Target(
                    profile_name=str(session.get("name", "")),
                    profile_dir=str(session.get("dir", "")),
                    url=str(row.get("url", "")),
                    title=str(row.get("title", "")),
                    windows=windows))
    return targets


def split_unaddressable(targets, pattern: str) -> tuple:
    """([addressable], [titleless]) — `selectWindow` can only pick a titled tab.

    A tab matched by URL whose title is empty has no title glob to select it
    with; the runner warns per skipped tab instead of pretending (RULE 4).
    """
    ok = [t for t in targets or [] if selector_for(t, pattern)]
    return ok, [t for t in targets or [] if not selector_for(t, pattern)]


def clashes(targets, pattern: str) -> list:
    """(selector, profile label, count) for selectors reused inside one profile.

    Two tabs sharing a title cannot be told apart by `title=` — the runner warns
    instead of pretending every run lands on its own tab (RULE 4).
    """
    counts: dict = {}
    for target in targets or []:
        key = (profile_label(target.profile_name, target.profile_dir),
               selector_for(target, pattern))
        counts[key] = counts.get(key, 0) + 1
    return [(selector, label, count) for (label, selector), count in counts.items()
            if count > 1]


def summarize(targets, real: bool) -> str:
    """The run plan in one line: how many runs, grouped per profile."""
    if not real:
        return f"{len(targets)} macro run(s) — one Firefox instance (no profile selection)"
    counts: dict = {}
    for target in targets or []:
        label = profile_label(target.profile_name, target.profile_dir) or "?"
        counts[label] = counts.get(label, 0) + 1
    parts = ", ".join(f"“{label}” ×{count}" for label, count in counts.items())
    return f"{len(targets)} macro run(s) — {parts}"


def runs(targets, pattern: str, config_dir, stamp: str) -> list:
    """Every target as a PlannedRun: selector, profile args, its own savelog."""
    total = len(targets or [])
    planned = []
    for index, target in enumerate(targets or [], 1):
        planned.append(PlannedRun(
            target=target, index=index, total=total, label=run_label(target),
            selector=selector_for(target, pattern),
            profile_args=launch.profile_args(target.profile_name, target.profile_dir),
            log_path=str(paths.log_file(config_dir, stamp, part=index if index > 1 else 0))))
    return planned
