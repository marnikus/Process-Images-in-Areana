"""Recovery backups for restore (audit R6 follow-on, RULE 18 split).

Before the first file moves, the CURRENT live values of every domain in the
run are snapshotted to `<config>/workspace_recovery/<utc>/` so any restore can
be undone by hand even without an undo timeline. Only files that exist are
backed up (a fresh machine legitimately lacks some); the manifest records the
absences.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .meta import config_dir, utc_now_iso


RECOVERY_DIR = "workspace_recovery"
RECOVERY_KEEP = 10


def _recovery_dir(bridge) -> Path:
    return config_dir(bridge) / RECOVERY_DIR / time.strftime("%Y%m%d-%H%M%S")


def _copy_live_file(path: Path, backup: Path, name: str) -> str | None:
    """Best-effort copy of one live file; None when absent (fresh machine) or unreadable."""
    if not path.exists():
        return None
    try:
        shutil.copy2(str(path), str(backup / name))
    except OSError:
        return None
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


def backup_live(bridge, providers: list) -> str:
    """Copy every affected live file into a recovery snapshot (task RESTORE 4).

    A live file that does not exist yet (fresh machine) is recorded under
    `absent` in recovery.json instead of failing the whole restore.
    """
    files = _affected_files(bridge, providers)
    if not files:
        return ""
    backup = _recovery_dir(bridge)
    backup.mkdir(parents=True, exist_ok=True)
    copied, absent = _copy_affected(files, backup)
    from app.persistence.workspace.integrity import canonical_bytes
    (backup / "recovery.json").write_bytes(canonical_bytes(
        {"created_utc": utc_now_iso(), "files": copied, "absent": absent}))
    prune_recovery(bridge)
    return str(backup)


def prune_recovery(bridge) -> None:
    """Keep the last RECOVERY_KEEP recovery snapshots (oldest removed, logged once)."""
    base = config_dir(bridge) / RECOVERY_DIR
    dirs = sorted(d for d in base.iterdir() if d.is_dir()) if base.exists() else []
    for stale in dirs[:-RECOVERY_KEEP]:
        shutil.rmtree(str(stale), ignore_errors=True)
