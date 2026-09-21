"""Readable tab ids — `{email}_{4 digits}`, pure math + parsing, no I/O.

The pool key stays the CDP tab id (identity, RULE 15); this module owns the
*display* handle a human can repeat: `marnikus@gmail.com_3045`. The owner
decision (2026-09-21) is that the 4-digit number is persisted per tab, so the
number is allocated once (highest used + 1, wrapping into the first free gap
past 9999) and never handed to a second tab. Imports: stdlib only.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Optional

ALIAS_MAX = 9999                # the 4-digit space the user asked for
ALIAS_WIDTH = 4
FALLBACK_PREFIX = "aka"         # tab whose account is not known (owner decision)
EMAIL_MAX = 64

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_STRIP_CHARS = " \t\r\n.,;:!?)]}>\"'"


def normalize_owner(owner: Any) -> str:
    """Display form of an account: trimmed, lowercased; only real emails survive."""
    if not isinstance(owner, str):
        return ""
    text = owner.strip().lower()
    if not text or len(text) > EMAIL_MAX or not _EMAIL_RE.fullmatch(text):
        return ""
    return text


def format_alias(owner: Any, no: Any) -> str:
    """`{owner-or-aka}_{4 digits}`; '' when this tab has no number yet."""
    if not isinstance(no, int) or isinstance(no, bool) or not 0 < no <= ALIAS_MAX:
        return ""
    return f"{normalize_owner(owner) or FALLBACK_PREFIX}_{no:0{ALIAS_WIDTH}d}"


def email_from_probe(raw: Any) -> str:
    """Probe reply (JSON string / dict / plain text) → one validated email or ''.

    Tolerant by design: the account row may move, so a reply that carries the
    address in prose still labels the tab — but a non-address never does.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8", "ignore")
        except Exception:
            return ""
    if isinstance(raw, str):
        return _email_in_text(raw)
    if isinstance(raw, dict):
        return _clean_value(raw.get("email"))
    if isinstance(raw, (list, tuple)):
        for item in raw:
            found = email_from_probe(item)
            if found:
                return found
    return ""


def _clean_value(value: Any) -> str:
    """One probe field → validated email (surrounding punctuation dropped)."""
    if not isinstance(value, str):
        return ""
    return normalize_owner(value.strip(_STRIP_CHARS))


def _email_in_text(text: str) -> str:
    """A string reply: JSON first (strict fields), else the first address in it."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        decoded = json.loads(text)
    except Exception:
        decoded = None
    if isinstance(decoded, (dict, list, tuple)):
        return email_from_probe(decoded)
    if isinstance(decoded, str):
        return _clean_value(decoded)
    found = _EMAIL_RE.search(text)
    return normalize_owner(found.group(0)) if found else ""


def _clean_numbers(taken: Iterable) -> set:
    """Integers inside the 4-digit space; anything else is junk."""
    out = set()
    for value in taken or ():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if 0 < value <= ALIAS_MAX:
            out.add(value)
    return out


def next_alias_no(taken: Iterable) -> int:
    """Highest used number + 1; wraps into the lowest free gap at 9999.

    Raises ValueError when every number is taken (9 999 live tabs).
    """
    used = _clean_numbers(taken)
    candidate = max(used) + 1 if used else 1
    if candidate <= ALIAS_MAX:
        return candidate
    for candidate in range(1, ALIAS_MAX + 1):
        if candidate not in used:
            return candidate
    raise ValueError("no free tab alias number left")


def clean_entry(no: Any, email: Any = "", seen: Any = 0.0) -> Optional[Dict[str, Any]]:
    """Validated persisted entry (`no` inside 1…9999); None when unusable."""
    if isinstance(no, bool) or not isinstance(no, int) or not 0 < no <= ALIAS_MAX:
        return None
    try:
        stamp = float(seen)
    except (TypeError, ValueError):
        stamp = 0.0
    owner = email if isinstance(email, str) else ""
    return {"no": no, "email": owner, "seen": stamp}


class AliasBook:
    """Per-tab 4-digit numbers + last known account; no file access.

    The book is the pool's source for the label: `no_for` allocates once per
    tab, `remember` refreshes the account without touching the number, and
    `as_dict` is the persisted shape (`config/cooldowns.json` → `aliases`).
    """

    def __init__(self, entries: Optional[Dict[str, Any]] = None, now: Any = None):
        self._now = now
        self._entries: Dict[str, Dict[str, Any]] = {}
        for tab_id, raw in dict(entries or {}).items():
            if not isinstance(tab_id, str) or not tab_id or not isinstance(raw, dict):
                continue
            clean = clean_entry(raw.get("no"), raw.get("email"), raw.get("seen"))
            if clean:
                self._entries[tab_id] = clean

    def _stamp(self) -> float:
        if callable(self._now):
            return float(self._now())
        import time as _time            # stdlib, lazy: keeps the module import-free
        return _time.time()

    def no_for(self, tab_id: str) -> int:
        """The tab's number, allocating a fresh one on first sight (0 when unusable)."""
        if not isinstance(tab_id, str) or not tab_id:
            return 0
        known = self._entries.get(tab_id)
        if known:
            return known["no"]
        no = next_alias_no(e["no"] for e in self._entries.values())
        self._entries[tab_id] = clean_entry(no, "", self._stamp())
        return no

    def owner_for(self, tab_id: str) -> str:
        """Last known account of the tab ('' when the probe has never answered)."""
        known = self._entries.get(tab_id)
        return normalize_owner(known.get("email")) if known else ""

    def label_for(self, tab_id: str) -> str:
        """Display handle of a *known* tab — never allocates a number."""
        known = self._entries.get(tab_id)
        return format_alias(known.get("email"), known.get("no")) if known else ""

    def remember(self, tab_id: str, owner: Any) -> None:
        """Store the account the probe reported; unknown tabs are left alone."""
        known = self._entries.get(tab_id) if isinstance(tab_id, str) else None
        if known is None:
            return
        owner = normalize_owner(owner)
        if owner:
            known["email"] = owner
        known["seen"] = self._stamp()

    def as_dict(self) -> Dict[str, Dict[str, Any]]:
        """Persisted shape (fresh copy; callers may keep it)."""
        return {tab_id: dict(entry) for tab_id, entry in self._entries.items()}

    def __len__(self) -> int:
        return len(self._entries)
