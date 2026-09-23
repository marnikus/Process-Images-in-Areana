"""Firefox's own files are the only honest eyes on its tabs — no debugger.

A normal Firefox exposes no tab list (that is the owner's rule), but it writes
files this app may READ (never control through): the session backups — modern
Firefox compresses them as `sessionstore-backups/recovery.jsonlz4` (the live
session, rewritten every ~15s; plain `recovery.json` died with Firefox v33),
`previous.jsonlz4`, and `sessionstore.jsonlz4` in the profile root — plus
`extensions.json` (the installed add-ons, the Ui.Vision extension among them).
Custom profile locations come from `profiles.ini` (`Path=` + `IsRelative=`),
so a profile outside the default roots is still seen. Every read is best
effort: a missing, locked or unparsable file answers "not seen", never an
error, so a wrong guess can never look like a browser verdict (RULE 4).
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


def ini_dirs(ini) -> list:
    """Profile dirs one `profiles.ini` names (`IsRelative=` honoured, [] when silent)."""
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


def _ini_sections(parser, base: Path) -> list:
    """Existing profile dirs from the parsed `[ProfileN]` sections (deduped)."""
    out = []
    for section in parser.sections():
        if not section.lower().startswith("profile"):
            continue
        path = (parser[section].get("Path") or "").strip()
        if not path:
            continue
        full = base / path if (parser[section].get("IsRelative") or "1").strip() != "0" \
            else Path(path).expanduser()
        if full.is_dir() and full not in out:
            out.append(full)
    return out


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


def _best_session(profiles) -> tuple:
    """(rows, windows, source, profile) of the freshest profile that answers."""
    best = ([], [], "", "")
    best_stamp = -1.0
    for profile in profiles or []:
        rows, windows, stamp, source = _profile_session(profile)
        if rows and stamp >= best_stamp:
            best, best_stamp = (rows, windows, source, Path(profile).name), stamp
    return best


def tab_rows(profiles=None) -> list:
    """Open tabs of the freshest readable profile ([] when none answers)."""
    rows, _windows, _source, _profile = _best_session(
        profiles if profiles is not None else profile_dirs())
    return rows


def session_windows(profiles=None) -> list:
    """Per-window [{"index","active","tabs"}] of the freshest readable profile."""
    _rows, windows, _source, _profile = _best_session(
        profiles if profiles is not None else profile_dirs())
    return windows


def session_source(profiles=None) -> tuple:
    """(file, profile) that fed the rows (("", "") when none answered)."""
    _rows, _windows, source, profile = _best_session(
        profiles if profiles is not None else profile_dirs())
    return source, profile


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
