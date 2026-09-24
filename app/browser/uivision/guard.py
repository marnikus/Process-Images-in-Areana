"""The protected-tab rule — pre-existing tabs must survive the run (pure).

`snapshot_tabs` freezes every open tab URL per profile before the first launch;
`verify_snapshot` diffs that freeze against a fresh session read after the last
verdict and answers one warning line per profile that lost a pre-existing tab.
The macro never closes tabs (the builder refuses `tab=open/close/closeallother`
by name), so a vanished tab was closed OUTSIDE the run — the warning says that
honestly instead of blaming the macro (RULE 4). No OS calls: sessions in, lines
out; the sequence reports the lines and the runner owns the reads.
"""

from __future__ import annotations

from .plan import profile_label

URLS_SHOWN = 3  # vanished URLs named per profile line; the rest fold into the count


def snapshot_tabs(sessions) -> dict:
    """{profile dir: frozenset(open tab URLs)} — the pre-launch freeze."""
    frozen = {}
    for session in sessions or []:
        urls = frozenset(str(row.get("url", "")) for row in session.get("rows") or []
                         if str(row.get("url", "")).strip())
        frozen[str(session.get("dir", ""))] = urls
    return frozen


def _current_urls(sessions) -> dict:
    """{profile dir: set(open tab URLs)} — the same shape, freshly read."""
    return {key: set(urls) for key, urls in snapshot_tabs(sessions).items()}


def _vanished_line(label: str, gone: set) -> str:
    """One profile's warning: which pre-existing tabs are no longer open."""
    shown = sorted(gone)[:URLS_SHOWN]
    tail = f" (+{len(gone) - URLS_SHOWN} more)" if len(gone) > URLS_SHOWN else ""
    examples = "; ".join(url[:90] for url in shown)
    return (f"profile “{label}”: {len(gone)} tab(s) open before the run are no "
            f"longer in the session store ({examples}{tail}) — the macro never "
            f"closes tabs, so they were closed outside the run")


def _labels(sessions) -> dict:
    """{profile dir: display label} — the ini name, else the dir basename."""
    return {str(session.get("dir", "")): profile_label(str(session.get("name", "")),
                                                      str(session.get("dir", "")))
            for session in sessions or []}


def verify_lines(snapshot: dict, rescan) -> list:
    """[(line, level)] — the protected-tab verdict (an unreadable store = one info line)."""
    try:
        fresh = rescan()
    except Exception:
        fresh = None
    if fresh is None:
        return [("post-run tab check skipped — the session store could not be "
                 "re-read", "info")]
    return [(line, "warn") for line in verify_snapshot(snapshot or {}, fresh)]


def verify_snapshot(snapshot: dict, sessions) -> list:
    """Warning lines for pre-existing tabs missing from the fresh read ([] = all kept).

    An empty fresh read answers [] — with no store readable (Firefox may have
    closed mid-run) there is nothing to diff against, and guessing damage from
    silence would be a false alarm (RULE 4).
    """
    if not sessions:
        return []
    current = _current_urls(sessions)
    labels = _labels(sessions)
    lines = []
    for profile_dir, before in (snapshot or {}).items():
        gone = set(before or ()) - current.get(profile_dir, set())
        if gone:
            lines.append(_vanished_line(labels.get(profile_dir) or
                                        profile_label("", profile_dir), gone))
    return lines
