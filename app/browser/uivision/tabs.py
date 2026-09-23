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

# The add-on's store id/name both carry one of these (old name: Kantu).
ADDON_NEEDLES = ("uivision", "kantu")


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


def profile_dirs() -> list:
    """Every existing profile directory under this OS's roots (may be empty)."""
    return _dirs_under(profile_roots(os.name, sys.platform,
                                     os.environ.get("APPDATA", ""), Path.home()))


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


def tab_rows(profiles=None) -> list:
    """Open tabs of the freshest readable profile ([] when none answers)."""
    best, best_stamp = [], -1.0
    for profile in (profiles if profiles is not None else profile_dirs()):
        store = Path(profile) / "sessionstore-backups" / "recovery.json"
        doc = _read_json(store)
        if not isinstance(doc, dict):
            continue
        try:
            stamp = store.stat().st_mtime
        except OSError:
            stamp = 0.0
        rows = _rows_of(doc)
        if rows and stamp >= best_stamp:
            best, best_stamp = rows, stamp
    return best


def addon_seen(profiles=None, needles=ADDON_NEEDLES):
    """True/False when one profile's extensions.json answers; None when none does."""
    for profile in (profiles if profiles is not None else profile_dirs()):
        doc = _read_json(Path(profile) / "extensions.json")
        if not isinstance(doc, dict):
            continue
        for addon in (doc.get("addons") or []):
            locale = addon.get("defaultLocale") or {}
            blob = f"{addon.get('id', '')} {addon.get('name', '')} {locale.get('name', '')}"
            flat = _flat(blob)
            if any(needle in flat for needle in needles):
                return True
        return False
    return None


def _flat(text: str) -> str:
    """Lowercase alphanumerics only — “Ui.Vision” and “uivision” are one name."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def match_urls(rows, pattern: str) -> list:
    """Open-tab URLs carrying the pattern (case-insensitive); blank matches none."""
    want = (pattern or "").strip().lower()
    if not want:
        return []
    return [row["url"] for row in (rows or []) if want in row["url"].lower()]
