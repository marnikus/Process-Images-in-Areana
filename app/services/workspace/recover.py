"""Recovery backups for restore (audit R6 follow-on, RULE 18 split).

Before the first file moves, the CURRENT live values of every domain in the
run are snapshotted to `<config>/workspace_recovery/<utc>/` so any restore can
be undone by hand even without an undo timeline. Only files that exist are
backed up (a fresh machine legitimately lacks some); the manifest records the
absences. A file that exists but cannot be copied, or a folder that cannot be
written, refuses the restore before anything changes — never an empty backup.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.persistence.workspace import fsio
from app.persistence.workspace.integrity import canonical_bytes
from .meta import config_dir, log_message, utc_now_iso


RECOVERY_DIR = "workspace_recovery"
RECOVERY_KEEP = 10


def _recovery_dir(bridge) -> Path:
    """A fresh folder per restore; a same-second collision gets -02, -03 … (still sorts)."""
    base = config_dir(bridge) / RECOVERY_DIR
    candidate = fsio.unique_dir(base, time.strftime("%Y%m%d-%H%M%S"))
    candidate.mkdir(parents=True)
    return candidate


def _copy_live_file(path: Path, backup: Path, name: str) -> str | None:
    """Copy one live file; None when absent (fresh machine). A failed copy raises OSError."""
    if not path.exists():
        return None
    shutil.copy2(str(path), str(backup / name))
    return name


def _affected_files(bridge, providers: list) -> dict:
    """{domain_id: [live Path, ...]} for every provider about to be restored."""
    files: dict = {}
    for provider in providers:
        for path in provider.live_paths(bridge):
            files.setdefault(provider.domain_id, []).append(path)
    return files


def _copy_affected(files: dict, backup: Path) -> tuple:
    """(copied, absent) — {domain_id: [name]} each; a missing live file is `absent`."""
    copied: dict = {}
    absent: dict = {}
    for domain_id, paths in files.items():
        for path in paths:
            name = _copy_live_file(path, backup, f"{domain_id}__{path.name}")
            (copied if name else absent).setdefault(domain_id, []).append(
                name or path.name)
    return copied, absent


def _fill_backup(backup: Path, files: dict) -> None:
    copied, absent = _copy_affected(files, backup)
    (backup / "recovery.json").write_bytes(canonical_bytes(
        {"created_utc": utc_now_iso(), "files": copied, "absent": absent}))


def backup_live(bridge, providers: list) -> tuple:
    """(backup path, "") or ("", refusal) — copy every affected live file (task RESTORE 4).

    A live file that does not exist yet (fresh machine) is recorded under
    `absent`; any copy/write failure removes the incomplete folder and refuses.
    """
    files = _affected_files(bridge, providers)
    if not files:
        return "", ""
    backup = None
    try:
        backup = _recovery_dir(bridge)
        _fill_backup(backup, files)
    except OSError as exc:
        if backup:
            shutil.rmtree(str(backup), ignore_errors=True)
        return "", (f"recovery backup failed ({exc}) — nothing was changed; "
                    "free the locked file or folder and retry")
    prune_recovery(bridge)
    return str(backup), ""


def prune_recovery(bridge) -> None:
    """Keep the last RECOVERY_KEEP recovery snapshots (oldest removed, logged once)."""
    base = config_dir(bridge) / RECOVERY_DIR
    dirs = sorted(d for d in base.iterdir() if d.is_dir()) if base.exists() else []
    stale = dirs[:-RECOVERY_KEEP]
    for folder in stale:
        shutil.rmtree(str(folder), ignore_errors=True)
    if stale:
        log_message(bridge, f"🧹 Workspace recovery: pruned {len(stale)} old backup(s) "
                            f"(keeping the last {RECOVERY_KEEP})")
