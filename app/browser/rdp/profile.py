"""Firefox prefs — what makes the DevTools socket reachable (2026-09-21, round 8).

`--start-debugger-server` is ignored unless `devtools.debugger.remote-enabled` is
set, and the server asks for a click on a connection prompt unless
`devtools.debugger.prompt-connection` is off. Those prefs live in the profile, so
the app writes them into `<profile>/user.js` — the documented override file that
Firefox re-reads at start, leaving the user's own `prefs.js` alone.

Three rules keep this acceptable on a **real** profile:

* it is explicit — the panel's Prepare Profile action asks for it, a plain Save
  never writes;
* it is additive — every unrelated line of an existing `user.js` survives;
* it is idempotent — a second run reports "already" and changes nothing.

The socket stays loopback-only (`devtools.debugger.force-local` is written true),
so the prefs never expose the browser on a network.

RULE 18: file ≤300, funcs ≤20, ≤3 params.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

USER_JS_NAME = "user.js"
PREF_TEMPLATE = 'user_pref("{name}", {value});'
NO_PREFS = "{label} is not a DevTools-server browser — nothing to write"


def pref_literal(value) -> str:
    """A pref value as JS: booleans lowercase, strings/numbers as JSON."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return json.dumps(value) if isinstance(value, (str, int, float)) else json.dumps(str(value))


def pref_line(name: str, value) -> str:
    """One `user_pref(...)` line."""
    return PREF_TEMPLATE.format(name=name, value=pref_literal(value))


def pref_names(text: str) -> List[str]:
    """Every pref name written in a `user.js` body."""
    names = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("user_pref(") and '",' in stripped:
            names.append(stripped.split("(", 1)[1].split('"')[1])
    return names


def user_js_text(profile) -> str:
    """The `user.js` body for one browser's DevTools prefs (one line per pref)."""
    return "".join(pref_line(name, value) + "\n" for name, value in (profile.prefs or ()))


def merge_user_js(existing: str, ours: str) -> str:
    """The file's unrelated lines plus ours — one line per pref, ours last (D-5)."""
    mine = set(pref_names(ours))
    kept = [line for line in (existing or "").splitlines() if line.strip() and not _replaced(line, mine)]
    return "".join(f"{line}\n" for line in kept + [l for l in ours.splitlines() if l.strip()])


def _replaced(line: str, mine: set) -> bool:
    """Does this existing line set a pref we are about to write ourselves?"""
    return line.strip().startswith("user_pref(") and any(
        f'"{name}"' in line for name in mine)


def merged_body(path: Path, ours: str) -> Tuple[str, bool]:
    """The body the file should have, and whether that differs from what is there."""
    before = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    after = merge_user_js(before, ours)
    return after, after != before


def prepare_profile(profile, data_dir) -> Tuple[dict, str]:
    """Write one browser's DevTools prefs into its profile; (result, error).

    An empty dir means the browser's own profile (round 10): for Firefox that is resolved from
    `profiles.ini`, because the pref that removes the Allow prompt only counts in the profile that
    is actually running.
    """
    ours = user_js_text(profile)
    if not ours:
        reason = NO_PREFS.format(label=profile.label)
        return {"ok": False, "changed": False, "message": reason}, reason
    target_dir = str(data_dir or "").strip()
    if not target_dir:
        from .. import firefox_profiles
        target_dir = firefox_profiles.used_profile_dir("")
    if not target_dir:
        reason = ("profile directory not found — this browser's own profile could not be located "
                  "(no profiles.ini) and the settings row names none")
        return {"ok": False, "changed": False, "message": reason}, reason
    return _write_prefs(Path(target_dir), ours, target_dir)


def _write_prefs(path: Path, ours: str, data_dir) -> Tuple[dict, str]:
    """The file half of `prepare_profile` (the dir check happens once)."""
    if not path.is_dir():
        reason = f"profile directory not found: {data_dir} — point the browser row at your real profile"
        return {"ok": False, "changed": False, "message": reason}, reason
    target = path / USER_JS_NAME
    body, changed = merged_body(target, ours)
    if not changed:
        message = f"{target} already has the DevTools prefs — restart Firefox to apply an earlier change"
        return {"ok": True, "changed": False, "prefs_file": str(target), "message": message}, ""
    target.write_text(body, encoding="utf-8")
    message = (f"DevTools prefs written to {target} (profile {data_dir}) — restart Firefox: "
               "a running instance does not re-read user.js")
    return {"ok": True, "changed": True, "prefs_file": str(target), "message": message}, ""
