"""Firefox's own files are the only honest eyes on its tabs — no debugger.

A normal Firefox exposes no tab list (that is the owner's rule), but it writes
two files this app may READ (never control through): the session store
(`sessionstore-backups/recovery.json` — every open tab's last URL and title)
and `extensions.json` (the installed add-ons, the Ui.Vision extension among
them). Both reads are best effort: a missing, locked or unparsable file
answers "not seen", never an error, so a wrong guess can never look like a
browser verdict (RULE 4).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import lz4

# Every place a running Firefox may keep the open-tab list, freshest first:
# the plain live backup, its compressed twins, the shutdown store.
STORE_RELS = ("sessionstore-backups/recovery.json",
              "sessionstore-backups/recovery.jsonlz4",
              "sessionstore.jsonlz4",
              "sessionstore-backups/previous.json",
              "sessionstore-backups/previous.jsonlz4")

# The add-on's store id/name both carry one of these (old name: Kantu).
ADDON_NEEDLES = ("uivision", "kantu")


def _nt_roots(env: dict) -> list:
    """Windows data dirs: APPDATA plus every Store package's cache."""
    roots = [Path(env["APPDATA"]) / "Mozilla" / "Firefox"] if env.get("APPDATA") else []
    if env.get("LOCALAPPDATA"):
        packages = Path(env["LOCALAPPDATA"]) / "Packages"
        roots += [pkg / "LocalCache" / "Roaming" / "Mozilla" / "Firefox"
                  for pkg in sorted(packages.glob("Mozilla*"))]
    return roots


def profile_roots(os_name: str, platform_name: str, env: dict, home: Path) -> list:
    """The Firefox data dirs of one OS — pure, so the rules are testable.

    Windows adds the Store install's package cache (a Store Firefox keeps its
    profiles under Packages\\Mozilla…\\LocalCache, not under APPDATA).
    """
    if os_name == "nt":
        return _nt_roots(env)
    if platform_name == "darwin":
        return [home / "Library" / "Application Support" / "Firefox"]
    return [home / ".mozilla" / "firefox",
            home / "snap" / "firefox" / "common" / ".mozilla" / "firefox"]


def _ini_profiles(ini: Path) -> list:
    """(path, is_relative) pairs one profiles.ini declares — pure string parse."""
    try:
        lines = ini.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out, state = [], {"path": "", "relative": True}
    for line in lines + ["[end]"]:
        _ini_line(line, state, out)
    return out


def _ini_line(line: str, state: dict, out: list) -> None:
    """One profiles.ini line: sections flush, Path=/IsRelative= accumulate."""
    text = line.strip()
    if text.startswith("["):
        if state["path"]:
            out.append((state["path"], state["relative"]))
        state["path"], state["relative"] = "", True
        return
    if text.startswith("Path="):
        state["path"] = text.split("=", 1)[1].strip()
    elif text.startswith("IsRelative="):
        state["relative"] = text.split("=", 1)[1].strip() != "0"


def _dirs_under(roots: list) -> list:
    """Existing sub-directories of each root — a refused root contributes none."""
    out = []
    for root in roots:
        try:
            out.extend(sorted(child for child in root.iterdir() if child.is_dir()))
        except OSError:
            continue
    return out


def _children(root: Path, os_name: str) -> list:
    """Where profiles live under one data dir: Profiles/ on Windows, itself else."""
    return _dirs_under([root / "Profiles"]) if os_name == "nt" else _dirs_under([root])


def profile_dirs(env=None, roots=None, os_name: str = "") -> list:
    """Every profile dir: root children + every profiles.ini-declared path."""
    environ = os.environ if env is None else env
    name = os_name or os.name
    if roots is None:
        roots = profile_roots(name, sys.platform, environ, Path.home())
    seen, out = set(), []
    for root in roots:
        for cand in _root_profiles(root, name):
            if cand.is_dir() and cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out


def _root_profiles(root: Path, name: str) -> list:
    """One data dir's profile dirs: its children plus its ini-declared paths."""
    declared = [ini_parent(root, p, rel) for p, rel in _ini_profiles(root / "profiles.ini")]
    return _children(root, name) + declared


def ini_parent(root: Path, path: str, relative: bool) -> Path:
    """One declared profile path resolved against its profiles.ini's dir."""
    return root / path if relative else Path(path)


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


def _read_store(path: Path):
    """One session-store file, plain JSON or jsonlz4 (None on any refusal)."""
    if str(path).endswith(".json"):
        return _read_json(path)
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    try:
        return json.loads(lz4.decompress(blob).decode("utf-8", "replace"))
    except Exception:
        return None


def _stamp(path: Path) -> float:
    """One file's mtime (0.0 when unreadable) — the freshness vote."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _profile_rows(profile) -> tuple:
    """(rows, mtime) of the best readable store file inside one profile."""
    best, stamp = [], -1.0
    for rel in STORE_RELS:
        file = Path(profile) / rel
        doc = _read_store(file)
        rows = _rows_of(doc) if isinstance(doc, dict) else []
        if rows and _stamp(file) >= stamp:
            best, stamp = rows, _stamp(file)
    return best, stamp


def lock_held(profile) -> bool:
    """A running Firefox holds parent.lock / .parentlock in its profile dir."""
    return any((Path(profile) / name).exists()
               for name in ("parent.lock", ".parentlock"))


def _rows_of(doc) -> list:
    """[{"url","title"}] — each tab's current entry in one session store."""
    rows = []
    for window in _list(doc.get("windows")):
        for tab in _list(window.get("tabs")):
            row = _tab_row(tab)
            if row:
                rows.append(row)
    return rows


def tab_rows(profiles=None) -> list:
    """Open tabs of the freshest readable profile ([] when none answers)."""
    best, best_stamp = [], -1.0
    for profile in (profiles if profiles is not None else profile_dirs()):
        rows, stamp = _profile_rows(profile)
        if rows and stamp >= best_stamp:
            best, best_stamp = rows, stamp
    return best


def addon_seen(profiles=None, needles=ADDON_NEEDLES):
    """True/False when one profile's extensions.json answers; None when none does."""
    saw_doc = False
    for profile in (profiles if profiles is not None else profile_dirs()):
        doc = _read_json(Path(profile) / "extensions.json")
        if not isinstance(doc, dict):
            continue
        saw_doc = True                      # a stale profile never votes for all
        for addon in (doc.get("addons") or []):
            if _addon_matches(addon, needles):
                return True
    return False if saw_doc else None


def _addon_matches(addon, needles) -> bool:
    """One extensions.json entry names the sought add-on (id or locale name)."""
    locale = addon.get("defaultLocale") or {}
    blob = f"{addon.get('id', '')} {addon.get('name', '')} {locale.get('name', '')}"
    return any(needle in _flat(blob) for needle in needles)


def _flat(text: str) -> str:
    """Lowercase alphanumerics only — “Ui.Vision” and “uivision” are one name."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def store_mtime(profiles=None):
    """Newest store-file stamp (None when no profile answers) — liveness clue."""
    stamps = [_stamp(Path(profile) / rel)
              for profile in (profiles if profiles is not None else profile_dirs())
              for rel in STORE_RELS]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def store_fresh(seconds: float, now: float = None, profiles=None) -> bool:
    """A session store written within `seconds` — Firefox is probably live."""
    stamp = store_mtime(profiles)
    if stamp is None:
        return False
    import time as _time
    return (now or _time.time()) - stamp <= seconds


def match_urls(rows, pattern: str) -> list:
    """Open-tab URLs carrying the pattern (case-insensitive); blank matches none."""
    want = (pattern or "").strip().lower()
    if not want:
        return []
    return [row["url"] for row in (rows or []) if want in row["url"].lower()]
