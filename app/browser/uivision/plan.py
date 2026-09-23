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


def plan_targets(sessions, pattern: str) -> list:
    """One Target per matching tab — every profile's rows, stable order.

    Matching runs over each session's flat `rows` (they exist for every shape —
    real stores and the anonymous seam alike); `windows` only decorates the
    Target for the foreground mapping.
    """
    want = (pattern or "").strip().lower()
    if not want:
        return []                      # a blank pattern matches none (never every tab)
    targets = []
    for session in sessions or []:
        windows = tuple(session.get("windows") or ())
        for row in session.get("rows") or []:
            if want in str(row.get("url", "")).lower():
                targets.append(Target(
                    profile_name=str(session.get("name", "")),
                    profile_dir=str(session.get("dir", "")),
                    url=str(row.get("url", "")),
                    title=str(row.get("title", "")),
                    windows=windows))
    return targets


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
