"""Open Firefox profiles — every running instance, not the last one written.

Owns which profiles are open and which of their tabs match the pattern.
Imports `profile_lock` / `tabs` / `mozlz4` / `launch` only (no Qt, no runner). A closed profile
is never a launch target: `-P` on a closed profile would start a browser the
user does not have open. The freshest session file is not special — a running
Firefox rewrites it every ~15 s, so "newest" was the last-focused profile and
every other open profile was skipped.
"""

from __future__ import annotations

import configparser
import os
import sys
import time
from pathlib import Path

from . import launch, mozlz4, tabs
from .profile_lock import safely_open

# A live Firefox rewrites recovery.jsonlz4 about every 15 s. Used only when
# the lock probe itself fails (unknown), never to override a lock that says closed.
FRESH_SECONDS = 90
PROFILE_FLAG = "-P"
PATH_FLAG = "--profile"


def session_fresh(profile, now=None, window: float = FRESH_SECONDS) -> bool:
    """True when a session file was written within `window` seconds."""
    stamp = time.time() if now is None else now
    for path in tabs._session_files(profile):
        try:
            age = stamp - path.stat().st_mtime
        except OSError:
            continue
        if 0 <= age <= window:
            return True
    return False


def _keep(profile) -> bool:
    """Open profiles always; unknown only when the session is still being written."""
    state = safely_open(profile)
    if state == "open":
        return True
    return state == "unknown" and session_fresh(profile)


def _resolved(section, base: Path):
    """The profile dir one `[ProfileN]` section names, or None when it is absent."""
    raw = (section.get("Path") or "").strip()
    if not raw:
        return None
    relative = (section.get("IsRelative") or "1").strip() != "0"
    full = base / raw if relative else Path(raw).expanduser()
    try:
        resolved = full.resolve()
    except OSError:
        return None
    return resolved if resolved.is_dir() else None


def names_in(text: str, base: Path) -> dict:
    """`{resolved path: Name}` from one `profiles.ini` body ({} when silent)."""
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text or "")
    except configparser.Error:
        return {}
    out = {}
    for section in parser.sections():
        if not section.lower().startswith("profile"):
            continue
        path = _resolved(parser[section], base)
        name = (parser[section].get("Name") or "").strip()
        if path and name:
            out[path] = name
    return out


def _ini_files() -> list:
    roots = tabs.profile_roots(os.name, sys.platform,
                               os.environ.get("APPDATA", ""), Path.home())
    return tabs._ini_candidates(roots)


def name_table(files=None) -> dict:
    """`{resolved profile path: Name}` from every readable `profiles.ini`."""
    out = {}
    for ini in (files if files is not None else _ini_files()):
        try:
            text = Path(ini).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.update(names_in(text, Path(ini).parent))
    return out


def profile_label(name: str, folder: str) -> str:
    """`Name [folder]` so the log names the profile the user knows and the dir."""
    text = (name or "").strip()
    leaf = folder or "?"
    return leaf if not text or text == leaf else f"{text} [{leaf}]"


def _window_tabs(window) -> list:
    """One window's tabs that have a URL, each tagged with its 0-based index."""
    out = []
    for index, tab in enumerate(tabs._list((window or {}).get("tabs"))):
        row = tabs._tab_row(tab)
        if row:
            out.append({**row, "index": index})
    return out


def _indexed_rows(doc) -> list:
    rows = []
    for window in tabs._list((doc or {}).get("windows")):
        rows.extend(_window_tabs(window))
    return rows


def read_session(profile) -> tuple:
    """(rows, windows, source) of the first session file that has tabs."""
    for path in tabs._session_files(profile):
        doc = mozlz4.read_session_file(path)
        if not isinstance(doc, dict):
            continue
        rows = _indexed_rows(doc)
        if rows:
            return rows, tabs._window_rows(doc), path.name
    return [], [], ""


def _session(path, names: dict) -> dict:
    folder = Path(path)
    try:
        resolved = folder.resolve()
    except OSError:
        resolved = folder
    name = names.get(resolved) or names.get(folder) or ""
    rows, windows, source = read_session(folder)
    return {"path": str(folder), "name": name, "folder": folder.name,
            "label": profile_label(name, folder.name), "source": source,
            "rows": rows, "windows": windows, "lock": safely_open(folder)}


def scan_open(dirs=None, names=None) -> tuple:
    """(open profile dicts, closed paths). Closed profiles are listed, not read."""
    paths = list(tabs.profile_dirs() if dirs is None else dirs)
    table = name_table() if names is None else names
    opened, closed = [], []
    for path in paths:
        (opened if _keep(path) else closed).append(path)
    return [_session(path, table) for path in opened], closed


def tab_matches(row, pattern: str) -> bool:
    """True when the pattern sits in the URL or the title (blank matches none)."""
    want = (pattern or "").strip().lower()
    if not want or not row:
        return False
    url = str(row.get("url") or "").lower()
    title = str(row.get("title") or "").lower()
    return want in url or want in title


def select_target(row, pattern: str) -> str:
    """`selectWindow` target for this tab — its exact title, else the pattern.

    An exact title does not use wildcards: `title=*Arena*` would also hit
    "Arena Chat". An untitled tab can only try the pattern (the log says so).
    """
    title = " ".join(str((row or {}).get("title") or "").split())
    if title:
        return f"title={title}"
    text = " ".join((pattern or "").split())
    return f"title=*{text}*" if text else ""


def _job(profile, row, target: str, skipped: bool) -> dict:
    return {"path": profile.get("path", ""), "name": profile.get("name", ""),
            "label": profile.get("label", ""), "windows": profile.get("windows") or [],
            "url": row.get("url", ""), "title": row.get("title", ""), "target": target,
            "skipped": skipped, "untitled": not str(row.get("title") or "").strip()}


def _jobs_for(profile, hits, pattern: str) -> list:
    """One job per hit; a repeated selectWindow target is skipped, not double-clicked."""
    seen = set()
    jobs = []
    for row in hits:
        target = select_target(row, pattern)
        key = (profile.get("path"), target)
        job = _job(profile, row, target, key in seen)
        job["matched"] = len(hits)
        seen.add(key)
        jobs.append(job)
    return jobs


def matching_jobs(profiles, pattern: str) -> list:
    """Every matching tab in every profile, in profile order then tab order."""
    jobs = []
    for profile in profiles or []:
        hits = [row for row in (profile.get("rows") or []) if tab_matches(row, pattern)]
        jobs.extend(_jobs_for(profile, hits, pattern))
    return jobs


def _banned(argv) -> list:
    found = {marker for arg in argv for marker in launch.BANNED_ARG_MARKERS
             if marker in str(arg).lower()}
    return sorted(found)


def profile_flag(name: str, path: str) -> tuple:
    """`(-P, name)` or `(--profile, path)`. A banned token is not a profile flag."""
    text = (name or "").strip()
    folder = (path or "").strip()
    # A name that starts with "-" is an argument, not a profile (`-P -foo`).
    if text and not text.startswith("-") and not _banned([text]):
        return PROFILE_FLAG, text
    if folder and not _banned([folder]):
        return PATH_FLAG, folder
    return "", ""


def argv_for(binary: str, url: str, job: dict) -> list:
    """`[binary, -P, name, url]` — never a bare URL when a profile is known.

    A bare `[binary, url]` is what Firefox hands to the last-used profile.
    Refusing that here is the bug fix, not a style choice. Debugger vocabulary
    stays banned (`launch.build_argv` plus a second pass over the profile token).
    """
    base = launch.build_argv(binary, url)
    flag, value = profile_flag(job.get("name") or "", job.get("path") or "")
    argv = [base[0], flag, value, base[1]] if flag else base
    bad = _banned(argv)
    if bad:
        raise ValueError(f"launch refuses debugger/driver vocabulary: {', '.join(bad)}")
    if not flag:
        raise ValueError("refusing a launch with no profile flag — that URL would "
                         "open in the last-used Firefox profile, not this one")
    return argv
