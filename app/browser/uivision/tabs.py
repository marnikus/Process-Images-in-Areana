"""Firefox's own files are the only honest eyes on its tabs — no debugger.

A normal Firefox exposes no tab list (that is the owner's rule), but it writes
files this app may READ (never control through): the session backups — modern
Firefox compresses them as `sessionstore-backups/recovery.jsonlz4` (the live
session, rewritten every ~15s; plain `recovery.json` died with Firefox v33),
`previous.jsonlz4`, and `sessionstore.jsonlz4` in the profile root — plus
`extensions.json` (the installed add-ons, the Ui.Vision extension among them).
EVERY profile is read (2026-09-23 multi-profile fix): `profile_sessions()`
answers one row per readable profile — the old freshest-only pick is gone, so
two running Firefox profiles are both seen. Custom profile locations come from
`profiles.ini` (`Path=` + `IsRelative=`, plus `Name=` — the `-P` handle that
lets a run address that profile's instance). Every read is best effort: a
missing, locked or unparsable file answers "not seen", never an error, so a
wrong guess can never look like a browser verdict (RULE 4).
"""

from __future__ import annotations

import configparser
import json
import os
import sys
from pathlib import Path

from . import mozlz4

# The add-on's store id/name both carry one of these (old name: Kantu).
ADDON_NEEDLES = ("uivision", "kantu")

# Session candidates in preference order — the live backup first, the legacy
# plain file and the older snapshots as fallbacks (the root-level snapshot
# is last: it only refreshes when Firefox shuts down cleanly).
BACKUPS_DIR = "sessionstore-backups"
BACKUP_CANDIDATES = ("recovery.jsonlz4", "recovery.json", "previous.jsonlz4")
ROOT_CANDIDATE = "sessionstore.jsonlz4"


def profile_roots(os_name: str, platform_name: str, appdata: str, home: Path) -> list:
    """The Firefox profile roots of one OS — pure, so the rules are testable."""
    if os_name == "nt":
        return [Path(appdata) / "Mozilla" / "Firefox" / "Profiles"] if appdata else []
    if platform_name == "darwin":
        return [home / "Library" / "Application Support" / "Firefox" / "Profiles"]
    return [home / ".mozilla" / "firefox",
            home / "snap" / "firefox" / "common" / ".mozilla" / "firefox"]


def _dirs_under(roots: list) -> list:
    """Existing sub-directories of each root — a refused root contributes none."""
    out = []
    for root in roots:
        try:
            out.extend(sorted(child for child in root.iterdir() if child.is_dir()))
        except OSError:
            continue
    return out


def _ini_candidates(roots: list) -> list:
    """Where `profiles.ini` may name custom profile paths (deduped, may be absent)."""
    out = []
    for root in roots:
        for ini in (Path(root) / "profiles.ini", Path(root).parent / "profiles.ini"):
            if ini not in out:
                out.append(ini)
    return out


def ini_entries(ini) -> list:
    """[(dir, name)] — every existing profile one `profiles.ini` names, ini order."""
    try:
        text = Path(ini).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        return []
    return _ini_sections(parser, Path(ini).parent)


def ini_dirs(ini) -> list:
    """Profile dirs one `profiles.ini` names (`IsRelative=` honoured, [] when silent)."""
    return [path for path, _name in ini_entries(ini)]


def _ini_sections(parser, base: Path) -> list:
    """[(dir, name)] from the parsed `[ProfileN]` sections (deduped by dir).

    `Name=` is the `-P` handle: Firefox's per-profile remoting hands a URL to
    the running instance of the NAMED profile, so a profile without a name can
    only be addressed by directory (`-profile <dir>`).
    """
    out, seen = [], []
    for section in parser.sections():
        if not section.lower().startswith("profile"):
            continue
        entry = _ini_entry(parser[section], base)
        if entry is not None and entry[0] not in seen:
            seen.append(entry[0])
            out.append(entry)
    return out


def _ini_entry(section, base: Path) -> tuple | None:
    """(dir, name) when the section names an existing dir, else None."""
    path = (section.get("Path") or "").strip()
    if not path:
        return None
    relative = (section.get("IsRelative") or "1").strip() != "0"
    full = base / path if relative else Path(path).expanduser()
    return (full, (section.get("Name") or "").strip()) if full.is_dir() else None


def profile_dirs() -> list:
    """Every profile dir: the default roots' children plus `profiles.ini` paths."""
    roots = profile_roots(os.name, sys.platform,
                           os.environ.get("APPDATA", ""), Path.home())
    found = _dirs_under(roots)
    for ini in _ini_candidates(roots):
        for path in ini_dirs(ini):
            if path not in found:
                found.append(path)
    return found


def _read_json(path: Path):
    """The parsed document, or None on any refusal (locked, gone, unparsable)."""
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _list(value) -> list:
    """A JSON array or nothing — junk types contribute no rows."""
    return value if isinstance(value, list) else []


def _tab_row(tab) -> dict:
    """The tab's current entry as {"url","title"} (None when it has none)."""
    entries = _list((tab or {}).get("entries"))
    last = entries[-1] if entries else {}
    url = str((last or {}).get("url") or "")
    return {"url": url, "title": str(last.get("title") or "")} if url else None


def _rows_of(doc) -> list:
    """[{"url","title"}] — each tab's current entry in one session store."""
    rows = []
    for window in _list(doc.get("windows")):
        for tab in _list(window.get("tabs")):
            row = _tab_row(tab)
            if row:
                rows.append(row)
    return rows


def _selected(row_count: int, window) -> int:
    """The active tab's 0-based index (`selected` is 1-based; -1 when unknown)."""
    try:
        pos = int((window or {}).get("selected", 0)) - 1
    except (TypeError, ValueError):
        return -1
    return pos if 0 <= pos < row_count else -1


def _window_rows(doc) -> list:
    """Per-window [{"index","active","tabs"}] — the OS-window mapping's raw half."""
    out = []
    for index, window in enumerate(_list(doc.get("windows")), 1):
        rows = []
        for tab in _list((window or {}).get("tabs")):
            row = _tab_row(tab)
            if row:
                rows.append(row)
        pos = _selected(len(rows), window)
        active = rows[pos] if pos >= 0 else (rows[-1] if rows else {"url": "", "title": ""})
        out.append({"index": index, "active": active, "tabs": rows})
    return out


def _session_files(profile) -> list:
    """One profile's session candidates, preference order (may all be absent)."""
    backups = Path(profile) / BACKUPS_DIR
    return [backups / name for name in BACKUP_CANDIDATES] + [Path(profile) / ROOT_CANDIDATE]


def _profile_session(profile) -> tuple:
    """(rows, windows, stamp, source) of the first candidate that answers."""
    for path in _session_files(profile):
        doc = mozlz4.read_session_file(path)
        if not isinstance(doc, dict):
            continue
        rows = _rows_of(doc)
        if not rows:
            continue
        try:
            stamp = path.stat().st_mtime
        except OSError:
            stamp = 0.0
        return rows, _window_rows(doc), stamp, path.name
    return [], [], -1.0, ""


def profile_names(roots=None) -> dict:
    """{profile dir → profiles.ini `Name=`} — the `-P` handle ('' when unnamed)."""
    if roots is None:
        roots = profile_roots(os.name, sys.platform,
                              os.environ.get("APPDATA", ""), Path.home())
    names: dict = {}
    for ini in _ini_candidates(roots):
        for path, name in ini_entries(ini):
            if path not in names or (name and not names[path]):
                names[path] = name
    return names


def profile_sessions(profiles=None) -> list:
    """EVERY readable profile, stable order — the multi-profile eyes.

    One row per answering profile: `{"name", "dir", "rows", "windows",
    "source", "stamp"}` (`name` is the `profiles.ini` handle). The old
    freshest-only pick is gone: two running profiles are BOTH seen.
    """
    dirs = profiles if profiles is not None else profile_dirs()
    names = profile_names()
    sessions = []
    for profile in dirs or []:
        rows, windows, stamp, source = _profile_session(profile)
        if rows:
            sessions.append({"name": names.get(Path(profile), ""), "dir": str(profile),
                             "rows": rows, "windows": windows,
                             "source": source, "stamp": stamp})
    return sessions


def _label(session: dict) -> str:
    """The session's display name: ini name, else the directory's basename."""
    return session.get("name") or Path(session.get("dir") or "").name


def tab_rows(profiles=None) -> list:
    """Open tabs of EVERY readable profile ([] when none answers)."""
    return [row for session in profile_sessions(profiles) for row in session["rows"]]


def session_windows(profiles=None) -> list:
    """Per-window rows of EVERY readable profile — profile-attributed, renumbered."""
    out = []
    for session in profile_sessions(profiles):
        for window in session["windows"]:
            out.append({**window, "profile": _label(session)})
    for index, window in enumerate(out, 1):
        window["index"] = index
    return out


def session_source(profiles=None) -> tuple:
    """(file, profile) of the freshest answering profile (("", "") when none)."""
    sessions = profile_sessions(profiles)
    if not sessions:
        return "", ""
    best = max(sessions, key=lambda session: session["stamp"])
    return best["source"], Path(best["dir"]).name


def addon_seen(profiles=None, needles=ADDON_NEEDLES):
    """True when any profile names the add-on; False when ≥1 answers; else None."""
    readable = False
    for profile in (profiles if profiles is not None else profile_dirs()):
        doc = _read_json(Path(profile) / "extensions.json")
        if not isinstance(doc, dict):
            continue
        readable = True
        for addon in (doc.get("addons") or []):
            if _addon_matches(addon or {}, needles):
                return True
    return False if readable else None


def _addon_matches(addon: dict, needles) -> bool:
    """True when the add-on's id, names or install URI carry a needle."""
    locale = addon.get("defaultLocale") or {}
    local = addon.get("localization") or {}
    names = " ".join(str(entry.get("name", ""))
                     for entry in local.values() if isinstance(entry, dict))
    blob = (f"{addon.get('id', '')} {addon.get('name', '')} "
            f"{locale.get('name', '')} {names} {addon.get('rootURI', '')}")
    flat = _flat(blob)
    return any(needle in flat for needle in needles)


def _flat(text: str) -> str:
    """Lowercase alphanumerics only — “Ui.Vision” and “uivision” are one name."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def match_urls(rows, pattern: str) -> list:
    """Open-tab URLs carrying the pattern (case-insensitive); blank matches none."""
    want = (pattern or "").strip().lower()
    if not want:
        return []
    return [row["url"] for row in (rows or []) if want in row["url"].lower()]


def discover_firefox_profiles(roots=None) -> list:
    """Discovered Firefox profiles as [{'name': str, 'dir': str, 'label': str}]."""
    dirs = profile_dirs() if roots is None else _dirs_under(roots)
    names = profile_names(roots=roots)
    out = []
    for d in dirs:
        p = Path(d)
        name = names.get(p, "")
        out.append({"name": name, "dir": str(p), "label": name or p.name})
    return out
