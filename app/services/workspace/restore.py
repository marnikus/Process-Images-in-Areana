"""Workspace restore — preview + the RESTORE algorithm (design §C.6).

Per domain, in topological order: safe-path → checksum → parse → schema →
semantic → migration gates, then a transactional apply with per-domain
rollback (the pre-apply capture re-applied). One failing domain is
recorded and skipped together with its strict dependents; independent
domains always continue and are never rolled back. Before the first apply
every affected live file is copied to a recovery snapshot. Stale live
state is reconciled afterwards — never resurrected. No Qt.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from app.persistence.workspace import fsio
from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import file_sha, safe_rel_path
from app.persistence.workspace.manifest import entry_for, read_manifest
from . import reports
from .coordinator import config_dir, utc_now_iso
from .registry import RESTORE_ORDER, get

RECOVERY_DIR = "workspace_recovery"
RECOVERY_KEEP = 10


def _preview_row(root: Path, manifest: dict, domain_id: str) -> dict:
    entry = entry_for(manifest, domain_id) or {}
    row = {"domain_id": domain_id, "display_name": entry.get("display_name", domain_id),
           "required": entry.get("required", False),
           "sensitivity": entry.get("sensitivity", "public"),
           "dependencies": entry.get("dependencies", {})}
    if not entry:
        row.update(status="not_in_manifest", note="domain unknown to this snapshot")
        return row
    if entry.get("capture", {}).get("excluded") or not entry.get("path"):
        row.update(status="excluded", note=entry.get("capture", {}).get(
            "excluded_reason", "policy-excluded"))
        return row
    rel, path = entry["path"], root / entry["path"]
    if not path.exists():
        row.update(status="missing", file=rel)
        return row
    actual = path.stat().st_size
    row.update(file=rel, bytes=entry.get("bytes"), schema_version=entry.get("schema_version"))
    if actual != entry.get("bytes"):
        row.update(status="size_mismatch", note=f"on disk {actual} bytes")
    else:
        row.update(status="ok")
    return row


def preview_restore(root) -> dict:
    """Manifest-only preview before any mutation (task RESTORE 1)."""
    root = Path(root)
    manifest, err = read_manifest(root)
    if err:
        return {"ok": False, "error": err}
    domains = [_preview_row(root, manifest, d) for d in
               [x for x in RESTORE_ORDER if x in manifest.get("domains", {})]
               + [x for x in manifest.get("domains", {}) if x not in RESTORE_ORDER]]
    return {"ok": True, **reports.preview_report(
        root=str(root), manifest=manifest, domains=domains,
        remap=_remap_notes(root, manifest))}


def _remap_notes(root: Path, manifest: dict) -> list:
    """Path-based resources that need user attention on this machine."""
    notes = []
    entry = entry_for(manifest, "arena_state")
    if entry and entry.get("path"):
        try:
            doc = json.loads((root / entry["path"]).read_text(encoding="utf-8"))
            folder_root = (doc.get("folder") or {}).get("root_path", "")
            if folder_root and not Path(folder_root).exists():
                notes.append(f"folder root not found on this machine: {folder_root} — "
                             "restore, then re-pick the folder (queue rows keep their statuses)")
        except (OSError, ValueError):
            pass
    return notes


def _selected_ids(manifest: dict, selected) -> list:
    """Manifest ids for this restore.

    Default (selected=None) restores every domain that owns a file; the
    policy domains (secret keys, recordings) appear in the preview and the
    manifest with their exclusion reason, and join only when explicitly
    selected — then they answer with their policy row, never a silent skip.
    """
    ids = list(manifest.get("domains", {}).keys())
    if selected is None:
        return [i for i in ids if (entry_for(manifest, i) or {}).get("path")]
    wanted = set(selected)
    return [i for i in ids if i in wanted]


def _restore_order(ids: set) -> list:
    """Registry order first, unknown-manifest ids after (never lose a domain)."""
    known = [i for i in RESTORE_ORDER if i in ids]
    return known + sorted(ids - set(RESTORE_ORDER))


def _selection_providers(manifest: dict, selected) -> tuple:
    """Providers for this restore + unknown-id rows (manifest is the only registry)."""
    unknown = [s for s in (selected or []) if s not in manifest.get("domains", {})]
    ordered = _restore_order(set(_selected_ids(manifest, selected)))
    providers = [get(i) for i in ordered]
    return [p for p in providers if p], unknown


def _strict_deps(provider) -> list:
    """Registered, resolvable strict dependencies of one provider."""
    return [dep for dep, kind in (provider.dependencies or {}).items()
            if kind == "strict" and get(dep)]


def _expand_strict(providers: list) -> list:
    """Strict dependencies ride along automatically (task RESTORE 3) — transitively."""
    chosen = {p.domain_id for p in providers}
    pending = list(providers)
    while pending:
        for dep in _strict_deps(pending.pop()):
            if dep not in chosen:
                chosen.add(dep)
                pending.append(get(dep))
    return [p for p in (get(i) for i in RESTORE_ORDER) if p and p.domain_id in chosen]


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


def _backup_live(bridge, providers: list) -> str:
    """Copy every affected live file into a recovery snapshot (task RESTORE 4).

    A live file that does not exist yet (fresh machine) is recorded under
    `absent` in recovery.json instead of failing the whole restore.
    """
    files = {}
    for provider in providers:
        for path in provider.live_paths(bridge):
            files.setdefault(provider.domain_id, []).append(path)
    if not files:
        return ""
    backup = _recovery_dir(bridge)
    backup.mkdir(parents=True, exist_ok=True)
    copied, absent = {}, {}
    for domain_id, paths in files.items():
        for path in paths:
            name = _copy_live_file(path, backup, f"{domain_id}__{path.name}")
            (copied if name else absent).setdefault(domain_id, []).append(
                name or path.name)
    from app.persistence.workspace.integrity import canonical_bytes
    (backup / "recovery.json").write_bytes(canonical_bytes(
        {"created_utc": utc_now_iso(), "files": copied, "absent": absent}))
    _prune_recovery(bridge)
    return str(backup)


def _prune_recovery(bridge) -> None:
    """Keep the last RECOVERY_KEEP recovery snapshots (oldest removed, logged once)."""
    base = config_dir(bridge) / RECOVERY_DIR
    dirs = sorted(d for d in base.iterdir() if d.is_dir()) if base.exists() else []
    for stale in dirs[:-RECOVERY_KEEP]:
        shutil.rmtree(str(stale), ignore_errors=True)


def _load_files(root: Path, manifest: dict, providers: list) -> dict:
    """rel → parsed doc or WorkspaceError — checksum + parse gates once per file."""
    docs: dict = {}
    for provider in providers:
        entry = entry_for(manifest, provider.domain_id) or {}
        rel = entry.get("path")
        if not rel:
            continue
        if rel in docs:
            continue
        docs[rel] = _load_one(root, entry, rel)
    return docs


def _load_one(root: Path, entry: dict, rel: str):
    safe = safe_rel_path(rel)
    if not safe or rel != safe:
        return WorkspaceError(entry_owner(entry), "unsafe_path", f"unsafe path: {rel!r}")
    path = root / safe
    if not path.exists():
        return WorkspaceError(entry_owner(entry), "missing", f"file missing: {safe}")
    if entry.get("bytes") is not None and path.stat().st_size != entry["bytes"]:
        return WorkspaceError(entry_owner(entry), "checksum",
                              f"size mismatch ({path.stat().st_size} ≠ {entry['bytes']})",
                              evidence=(entry.get("bytes"), path.stat().st_size))
    if entry.get("sha256") and file_sha(path) != entry["sha256"]:
        return WorkspaceError(entry_owner(entry), "checksum",
                              "sha-256 mismatch — file changed after save",
                              evidence=(entry.get("sha256", "")[:12], file_sha(path)[:12]))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return WorkspaceError(entry_owner(entry), "parse", f"invalid JSON: {exc}")


def entry_owner(entry: dict) -> str:
    """Best-effort owner name for a file-level problem row."""
    return entry.get("display_name", "workspace file")
