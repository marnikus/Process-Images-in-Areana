"""The Ui.Vision address of one Firefox tab: "title + relative index" (pure, I-64).

`selectWindow title=G` activates the FIRST tab whose title matches the glob G
(Firefox `tabs.query` + MatchGlob: anchored, `*` = any run, `?` = one char), in
window order then strip order. `selectWindow tab=K` then lands K tabs to the
right of the focused window's active tab (the autostart tab has closed, so the
extension re-anchors there — see the 2026-09-25 design, section 2).

So the target E is addressed by the nearest tab T at or left of E, in E's
window, whose exact-title glob first-matches T itself. K = E.index − T.index,
and K = 0 means the title alone suffices. The emulation matches
case-INsensitively: that is a superset of Firefox's matches, so "T is the first
match" here implies the same in Firefox whichever case rule it uses.
Characters the extension would rewrite in a target (`"`, `\\`, `$`, control
chars, outer whitespace — targets are trimmed) become `?`, which still matches
them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

REWRITTEN = frozenset('"\\$')
TITLE_MAX = 120          # longer titles are clipped with `*` (still first-match checked)


@dataclass(frozen=True)
class Address:
    """How the macro reaches one tab: the anchor glob and the offset to the right of it."""

    anchor: str           # the `title=` glob (without the `title=` prefix)
    offset: int           # K ≥ 0 — tabs to the right of the anchor, same window
    anchor_index: int     # the anchor's 0-based strip index (for the log line)


def title_glob(title: str) -> str:
    """The exact-title glob the extension will receive unchanged ('' for a blank title)."""
    text = str(title or "")
    if not text.strip():
        return ""
    chars = ["?" if ch in REWRITTEN or ord(ch) < 32 else ch for ch in text]
    body = "".join(chars)
    lead = len(body) - len(body.lstrip())
    trail = len(body) - len(body.rstrip())
    glob = "?" * lead + body.strip() + "?" * trail
    return glob if len(glob) <= TITLE_MAX else glob[:TITLE_MAX] + "*"


def glob_regex(glob: str):
    """MatchGlob as a regex: anchored, `*` any run, `?` one char, case-insensitive."""
    parts = [".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in glob]
    return re.compile("".join(parts), re.IGNORECASE | re.DOTALL)


def first_match(windows: list, glob: str) -> Optional[tuple]:
    """(window no, index) of the first tab whose title matches `glob`, in session order."""
    rx = glob_regex(glob)
    for window_no, row in enumerate(windows, 1):
        for index, tab in enumerate(row):
            if rx.fullmatch(str(tab.get("title") or "")):
                return window_no, index
    return None


def locate(windows: list, window_no: int, index: int) -> Optional[Address]:
    """The nearest self-first-matching anchor at or left of the target; None when there is none."""
    if not 1 <= window_no <= len(windows) or not 0 <= index < len(windows[window_no - 1]):
        return None
    row = windows[window_no - 1]
    for pos in range(index, -1, -1):
        glob = title_glob(row[pos].get("title", ""))
        if glob and first_match(windows, glob) == (window_no, pos):
            return Address(anchor=glob, offset=index - pos, anchor_index=pos)
    return None


def refusal(windows: list, window_no: int, index: int) -> str:
    """Why a tab has no address — named, so the job's failure says what to change (RULE 4)."""
    if not 1 <= window_no <= len(windows) or not 0 <= index < len(windows[window_no - 1]):
        return "the tab is no longer at its recorded place in the session store"
    return (f"no tab at or left of it in window {window_no} has a title that is the FIRST "
            f"match in the profile — Ui.Vision's title + relative index cannot reach it; "
            f"give a tab to its left a unique title or move it into the first window")
