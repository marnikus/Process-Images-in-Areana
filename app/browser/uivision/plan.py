"""From sessions to runs — which profile, which tab, which selector (pure).

The multi-profile planner: `plan_targets` turns per-profile session rows into
`Target`s (every profile, every matching tab — never just the freshest), then
`one_per_profile` keeps the FIRST match of each profile — one macro run per
open profile (2026-09-24 owner rule; duplicate tabs never re-run a profile),
and `runs` renders each remaining target into a `PlannedRun` the runner
executes: its own `selectWindow` hard-fallback selector (the title pattern,
else the tab's own title glob — the `url=*…*` primary rides the macro file,
see `macro.build_commands`), its own profile argv prefix (`-P name`, or
`-profile dir` when no `profiles.ini` name exists — Firefox hands the URL to
THAT profile's running instance) and its own savelog file. Imports only
`paths` and `launch` from this package; no OS calls, no asyncio.
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
class Patterns:
    """The window's two tab filters as one value — matching's only input."""

    title: str = ""    # TAB TITLE PATTERN ('' = any title)
    url: str = ""      # TAB URL PATTERN ('' = any URL)


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


def matches(title, url, patterns: Patterns) -> bool:
    """(title, url) against two optional substrings — a blank pattern means any.

    The owner's rule (2026-09-24): empty title pattern = any title, empty URL
    pattern = any URL; a tab must satisfy BOTH filters to run.
    """
    want_title = (patterns.title or "").strip().lower()
    want_url = (patterns.url or "").strip().lower()
    if want_title and want_title not in (title or "").lower():
        return False
    return not want_url or want_url in (url or "").lower()


def describe_search(patterns: Patterns) -> str:
    """The active filters in one readable phrase (`any tab` when both are blank)."""
    title = (patterns.title or "").strip()
    url = (patterns.url or "").strip()
    if not title and not url:
        return ANY_TAB
    left = f'title “{title}”' if title else "any title"
    right = f'URL “{url}”' if url else "any URL"
    return f"{left} + {right}"


TITLE_SELECTOR_MAX = 40  # chars — long titles are fragile (session store may be stale)


def selector_for(target: Target, patterns: Patterns) -> str:
    """The HARD tab selector (cmd_var3): the title pattern, else the tab's title.

    Priority per the owner's rule (2026-09-24): the URL pattern is the primary
    locator and rides the macro file as a guarded first `selectWindow url=…`
    (see `macro.build_commands`); this value is the fallback that decides the
    run when that attempt fails (E209 today) — title pattern when set, else the
    matched tab's own title (clipped to TITLE_SELECTOR_MAX so stale session
    titles still match). Never constructed from foreground detection.
    """
    want = (patterns.title or "").strip()
    if want:
        return f"title=*{want}*"
    title = (target.title or "").strip()
    if not title:
        return ""
    clipped = title[:TITLE_SELECTOR_MAX] if len(title) > TITLE_SELECTOR_MAX else title
    return f"title=*{clipped}*"


def run_label(target: Target) -> str:
    """`profile “X” · tab “Y”` for the report lines (`tab “Y”` alone when unnamed)."""
    who = profile_label(target.profile_name, target.profile_dir)
    tab = (target.title or target.url or "?")[:TITLE_CLIP]
    return f'profile “{who}” · tab “{tab}”' if who else f'tab “{tab}”'


def plan_targets(sessions, patterns: Patterns) -> list:
    """One Target per tab matching BOTH patterns — every profile, stable order.

    A blank pattern matches any (owner rule, 2026-09-24): blank title + blank
    URL plan a run for every open tab. Matching runs over each session's flat
    `rows`; `windows` only decorates the Target for the foreground mapping.
    """
    targets = []
    for session in sessions or []:
        windows = tuple(session.get("windows") or ())
        for row in session.get("rows") or []:
            if matches(str(row.get("title", "")), str(row.get("url", "")), patterns):
                targets.append(Target(
                    profile_name=str(session.get("name", "")),
                    profile_dir=str(session.get("dir", "")),
                    url=str(row.get("url", "")),
                    title=str(row.get("title", "")),
                    windows=windows))
    return targets


def one_per_profile(targets) -> list:
    """The FIRST matching tab of each profile — one run per open profile.

    The owner's exact rule (2026-09-24, first-run fix): every profile with a
    matching tab runs the macro EXACTLY once — extra matching tabs in the same
    profile are reported as matches but never re-run it. The flat tabs seam
    (one anonymous profile) therefore also yields a single run. Order is kept.
    """
    out, seen = [], set()
    for target in targets or []:
        key = target.profile_dir or target.profile_name
        if key in seen:
            continue
        seen.add(key)
        out.append(target)
    return out


def split_unaddressable(targets, patterns: Patterns) -> tuple:
    """([addressable], [titleless]) — `selectWindow` can only pick a titled tab.

    A tab matched by URL whose title is empty has no title glob to select it
    with; the runner warns per skipped tab instead of pretending (RULE 4).
    """
    ok = [t for t in targets or [] if selector_for(t, patterns)]
    return ok, [t for t in targets or [] if not selector_for(t, patterns)]


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


def runs(targets, patterns: Patterns, config_dir, stamp: str) -> list:
    """Every target as a PlannedRun: selector, profile args, its own savelog."""
    total = len(targets or [])
    planned = []
    for index, target in enumerate(targets or [], 1):
        planned.append(PlannedRun(
            target=target, index=index, total=total, label=run_label(target),
            selector=selector_for(target, patterns),
            profile_args=launch.profile_args(target.profile_name, target.profile_dir),
            log_path=str(paths.log_file(config_dir, stamp, part=index if index > 1 else 0))))
    return planned
