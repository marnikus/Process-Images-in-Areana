"""From sessions to runs — which profile, which tab, which locator (pure).

The multi-profile planner: `plan_targets` turns per-profile session rows into
one `Target` per profile — the run unit is the PROFILE (owner rule 2026-09-24:
"every profile found with a tab — exact one time"; a profile with two matching
tabs still gets exactly one run), its first matching tab WITH a title being
the representative (a titleless tab cannot be selected — `selectWindow` has no
url= locator, and the extension throws E209 on one; see the design doc).
`runs` renders each target into a `PlannedRun` the runner executes: its own
`selectWindow` locator (built ONLY from the owner's configured patterns —
`selector_for`, never from a clipped detected title), its own profile argv
prefix (`-P name`, or `-profile dir` when no `profiles.ini` name exists —
Firefox hands the URL to THAT profile's running instance) and its own savelog
file. Imports only `paths` and `launch` from this package; no OS calls, no
asyncio.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from . import launch, paths

TITLE_CLIP = 40


@dataclass(frozen=True)
class Target:
    """One macro run's destination: the representative tab inside ONE profile."""

    profile_name: str = ""    # the profiles.ini name ('' = no `-P` handle known)
    profile_dir: str = ""     # the profile directory (the `-profile` fallback)
    url: str = ""
    title: str = ""
    windows: tuple = ()       # this profile's session windows (the foreground map)


@dataclass
class PlannedRun:
    """One macro run with every value rendered — the runner executes these in order.

    Deliberately mutable: right before its launch the sequence re-reads the
    tab's title and may rebuild `selector`/`label` from the fresh one.
    """

    target: Target
    index: int            # 1-based position in the sequence
    total: int
    label: str            # `profile “X” · tab “Y”` for the report lines
    selector: str         # cmd_var3 — the selectWindow target
    profile_args: tuple   # ("-P", name) / ("-profile", dir) / () — rides before the URL
    log_path: str         # this run's own savelog (run 1 keeps the plain name)


@dataclass(frozen=True)
class Search:
    """The owner's two tab filters, carried together — one concept, one object.

    `title` is the TAB TITLE PATTERN, `url` the TAB URL PATTERN (both blank =
    any). Matching requires BOTH; the locator priority is URL over title.
    """

    title: str = ""
    url: str = ""


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


def _profile_key(session: dict) -> str:
    """The run-unit key — the profile dir (the anonymous seam answers "")."""
    return str(session.get("dir") or "") or str(session.get("name") or "")


def plan_targets(sessions, search: Search) -> list:
    """One Target per profile — its first matching tab with a non-empty title.

    Stable session order; a titleless match is skipped for the representative
    (it cannot be selected) and `unmatchable_profiles` names the profiles left
    with nothing selectable.
    """
    targets, seen = [], set()
    for session in sessions or []:
        key = _profile_key(session)
        if key in seen:
            continue
        for row in session.get("rows") or []:
            title = str(row.get("title", ""))
            if not title.strip() or not matches(title, str(row.get("url", "")),
                                                search.title, search.url):
                continue
            seen.add(key)
            targets.append(Target(
                profile_name=str(session.get("name", "")),
                profile_dir=str(session.get("dir", "")),
                url=str(row.get("url", "")),
                title=title,
                windows=tuple(session.get("windows") or ())))
            break
    return targets


def _match_summary(session, search: Search) -> tuple:
    """(has_titled_match, titleless_match_count) of one profile's rows."""
    has_titled, titleless = False, 0
    for row in session.get("rows") or []:
        if not matches(str(row.get("title", "")), str(row.get("url", "")),
                       search.title, search.url):
            continue
        if str(row.get("title", "")).strip():
            has_titled = True
        else:
            titleless += 1
    return has_titled, titleless


def match_counts(sessions, search: Search) -> list:
    """[(label, count)] — profiles with ≥2 matching tabs: the one-run-per-profile warning."""
    out = []
    for session in sessions or []:
        label = profile_label(str(session.get("name", "")), str(session.get("dir", ""))) or "?"
        n = sum(1 for row in session.get("rows") or []
                if matches(str(row.get("title", "")), str(row.get("url", "")),
                           search.title, search.url))
        if n > 1:
            out.append((label, n))
    return out


def unmatchable_profiles(sessions, search: Search) -> list:
    """[(label, count)] — profiles whose matching tabs are ALL titleless (cannot run)."""
    out = []
    for session in sessions or []:
        has_titled, titleless = _match_summary(session, search)
        if titleless > 0 and not has_titled:
            label = profile_label(str(session.get("name", "")), str(session.get("dir", ""))) or "?"
            out.append((label, titleless))
    return out


def selector_for(target: Target, search: Search) -> str:
    """The run's selectWindow locator — from the owner's patterns, never detection.

    Owner's priority (2026-09-24): a title pattern alone → the pattern
    verbatim (`title=*pattern*`; Firefox globs `title=` since v59). A URL
    pattern (alone or both — URL wins) → the URL pattern is the deciding
    filter, and since `selectWindow` has no url= locator (the extension
    throws E209 on one), the transport is the matched tab's own FULL,
    unclipped title. Both blank → the representative tab's full title. A
    blank answer ("") means unaddressable, never a guess.
    """
    want_title = (search.title or "").strip()
    want_url = (search.url or "").strip()
    if not want_url and want_title:
        return f"title=*{want_title}*"
    title = (target.title or "").strip()
    return f"title=*{title}*" if title else ""


def retitled(target: Target, title: str) -> Target:
    """The same target with the launch-time-fresh title (the re-check's rebuild)."""
    return dataclasses.replace(target, title=title)


def run_label(target: Target) -> str:
    """`profile “X” · tab “Y”` for the report lines (`tab “Y”` alone when unnamed)."""
    who = profile_label(target.profile_name, target.profile_dir)
    tab = (target.title or target.url or "?")[:TITLE_CLIP]
    return f'profile “{who}” · tab “{tab}”' if who else f'tab “{tab}”'


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


def runs(targets, search: Search, config_dir, stamp: str) -> list:
    """Every target as a PlannedRun: locator from the patterns, profile args, savelog."""
    total = len(targets or [])
    planned = []
    for index, target in enumerate(targets or [], 1):
        planned.append(PlannedRun(
            target=target, index=index, total=total, label=run_label(target),
            selector=selector_for(target, search),
            profile_args=launch.profile_args(target.profile_name, target.profile_dir),
            log_path=str(paths.log_file(config_dir, stamp, part=index if index > 1 else 0))))
    return planned
