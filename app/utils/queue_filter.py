"""Queue filtering by the _AI output suffix (pure, no app imports).

Generated outputs are `{base}_AI{ext}` or `{base}_AI_{n}{ext}`; matching
on the stem keeps `my_AI_photo.png` (suffix not at the end) untouched.
"""

from __future__ import annotations

import os
import re

AI_SUFFIX = "_AI"
_AI_RE = re.compile(r"_AI(_\d+)?$")


def is_ai_output(filename: str) -> bool:
    """True when the file stem ends with the _AI output suffix."""
    try:
        stem = os.path.splitext(os.path.basename(filename or ""))[0]
    except Exception:
        return False
    return bool(stem) and _AI_RE.search(stem) is not None
