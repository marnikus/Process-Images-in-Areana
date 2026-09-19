"""D6: vulture @90 whitelist — only findings NOT listed here fail the gate.

Entries are (relative_file, symbol_name) pairs, stable across line moves.
Regenerate the list from the current tree (accepting all current findings):
    python tools/vulture_whitelist.py --update
The lane in tools/pre_push_check.sh fails on any NEW vulture @90 finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# (file, name) — empty means the tree is vulture-clean at @90
WHITELIST: list[tuple[str, str]] = []

_FINDING_RE = re.compile(r"^(?P<file>\S+?):\d+:\s+[\w ]+ '(?P<name>[^']+)' \(\d+% confidence\)")


def parse_vulture_output(text: str) -> set[tuple[str, str]]:
    """'file:line: unused function 'name' (90% confidence)' -> {(file, name)}"""
    out: set[tuple[str, str]] = set()
    for line in text.splitlines():
        m = _FINDING_RE.match(line.strip())
        if m:
            out.add((m.group("file"), m.group("name")))
    return out


def _update_whitelist() -> None:
    import subprocess
    root = Path(__file__).resolve().parent.parent
    res = subprocess.run(
        [sys.executable, "-m", "vulture", "app", "--min-confidence", "90"],
        cwd=str(root), capture_output=True, text=True)
    findings = sorted(parse_vulture_output(res.stdout))
    here = Path(__file__).resolve()
    text = here.read_text(encoding="utf-8")
    new_block = "WHITELIST: list[tuple[str, str]] = [\n"
    new_block += "".join(f"    ({f!r}, {n!r}),\n" for f, n in findings)
    new_block += "]"
    text = re.sub(r"WHITELIST: list\[tuple\[str, str\]\] = \[.*?\]",
                  lambda _m: new_block, text, count=1, flags=re.DOTALL)
    here.write_text(text, encoding="utf-8")
    print(f"whitelist updated: {len(findings)} findings")


if __name__ == "__main__":
    if "--update" in sys.argv:
        _update_whitelist()
    else:
        print("usage: python tools/vulture_whitelist.py --update")
