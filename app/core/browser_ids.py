"""Pure browser-identity primitives — safe for every layer (RULE 20).

Both dispatchers, the reconciler and the browser package share these three
names: which browser id a page carries (chrome/firefox), what the URL list's
Conn cell shows for it, and how a discovered Firefox tab's stable key is
built and recognised (`{profileDir}_tab{n}` — design D-2). Pure strings and
one regex: no I/O, no Qt, no browser package — so `services/live` can use
them without breaking the ui/browser import boundary.
"""

from __future__ import annotations

import re
from typing import Any

CHROME = "chrome"   # the pool's default browser id (CDP lane)
FIREFOX = "firefox"  # the pool's browser id for the Ui.Vision lane (D-4)

# `{profileBase}_tab{n}` — greedy profile so `a_b_tab12` splits as `a_b` / 12.
TAB_ID_RE = re.compile(r"^(?P<profile>.+)_tab(?P<index>\d+)$")


def is_firefox(value: Any) -> bool:
    """True for the firefox browser id or any object carrying one (page/tab)."""
    if isinstance(value, str):
        return value == FIREFOX
    return getattr(value, "browser", "") == FIREFOX


def is_tab_id(tab_id: Any) -> bool:
    """True when this key is a discovered Firefox tab (never a CDP target id)."""
    return isinstance(tab_id, str) and bool(TAB_ID_RE.match(tab_id))
