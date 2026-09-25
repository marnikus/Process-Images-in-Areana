"""Workspace restore — the whole MUTATING side (design §C.6/§F).

Selection + strict-dependency expansion, recovery backup of live files,
the file gates (safe-path → checksum → parse), the per-domain transaction
(dependency → schema → migration → semantic → apply with rollback to the
pre-apply capture), derived-state reconcile, and the restore-report written
into the workspace folder. The read-only preview lives in `restore.py`.
"""

from __future__ import annotations

from pathlib import Path

import json
import shutil
import time
from pathlib import Path

from app.persistence.workspace import fsio
from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import canonical_bytes, file_sha, safe_rel_path
from app.persistence.workspace.manifest import entry_for, read_manifest
from . import reports
from .meta import config_dir, log_message, utc_now_iso
from .registry import RESTORE_ORDER, get, restore_order
from .save import record_restore

RECOVERY_DIR = "workspace_recovery"
RECOVERY_KEEP = 10


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


def selection_providers(manifest: dict, selected) -> tuple:
    """Providers for this restore + unknown-id rows (manifest is the only registry)."""
    unknown = [s for s in (selected or []) if s not in manifest.get("domains", {})]
    ordered = restore_order(set(_selected_ids(manifest, selected)))
    providers = [get(i) for i in ordered]
    return [p for p in providers if p], unknown


def _strict_deps(provider) -> list:
    """Registered, resolvable strict dependencies of one provider."""
    return [dep for dep, kind in (provider.dependencies or {}).items()
            if kind == "strict" and get(dep)]


def expand_strict(providers: list) -> list:
    """Strict dependencies ride along automatically (task RESTORE 3) — transitively."""
    chosen = {p.domain_id for p in providers}
    pending = list(providers)
    while pending:
        for dep in _strict_deps(pending.pop()):
            if dep not in chosen:
                chosen.add(dep)
                pending.append(get(dep))
    ordered_ids = restore_order(set(chosen))
    return [p for p in (get(i) for i in ordered_ids) if p]


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


def backup_live(bridge, providers: list) -> str:
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


def load_files(root: Path, manifest: dict, providers: list) -> dict:
    """rel → parsed doc or WorkspaceError — checksum + parse gates once per file."""
    docs: dict = {}
    for provider in providers:
        entry = entry_for(manifest, provider.domain_id) or {}
        rel = entry.get("path")
        if not rel:
            continue
        if rel in docs:
            continue
        docs[rel] = load_one(root, entry, rel)
    return docs


def load_one(root: Path, entry: dict, rel: str):
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
    actual_sha = file_sha(path)
    if entry.get("sha256") and actual_sha != entry["sha256"]:
        return WorkspaceError(entry_owner(entry), "checksum",
                              "sha-256 mismatch — file changed after save",
                              evidence=(entry.get("sha256", "")[:12], actual_sha[:12]))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return WorkspaceError(entry_owner(entry), "parse", f"invalid JSON: {exc}")


def entry_owner(entry: dict) -> str:
    """Best-effort owner name for a file-level problem row."""
    return entry.get("display_name", "workspace file")


def _skip_row(provider, error: WorkspaceError) -> dict:
    return {"domain_id": provider.domain_id, "status": "skipped", **error.to_dict()}


def _version_row(provider, entry: dict) -> dict | None:
    """Schema gate: unsupported future versions are refused precisely (task rule 3)."""
    version = entry.get("schema_version")
    if version in provider.supported_migrations:
        return None
    error = WorkspaceError(
        provider.domain_id, "schema",
        f"saved schema version {version!r} is not supported by this build "
        f"(supported: {', '.join(provider.supported_migrations)})",
        evidence=(", ".join(provider.supported_migrations), version))
    return _skip_row(provider, error)


def _policy_row(provider, entry: dict) -> dict:
    """A domain with no file (secret / opt-out policy) — never applied, always explained."""
    cause = (entry.get("capture", {}) or {}).get("excluded_reason", "policy-excluded domain")
    row = {"domain_id": provider.domain_id, "status": "skipped",
           "stage": "apply", "policy": True, "cause": cause}
    advice = getattr(provider, "restore_advice", "")
    if advice:
        row["recommended_action"] = advice
    return row


def _rollback(bridge, provider, previous, exc: Exception) -> dict:
    """Roll back to the pre-apply capture; an impossible rollback is `damaged`, loud."""
    if previous.ok and previous.doc is not None and not previous.excluded:
        try:
            provider.apply(bridge, previous.doc)
        except Exception as rb_exc:
            return {"domain_id": provider.domain_id, "status": "damaged",
                    "stage": "rollback",
                    "cause": f"apply failed: {exc}; rollback also failed: {rb_exc} — "
                             "use the recovery snapshot named in the report",
                    "recommended_action": "restore by hand from the recovery folder"}
    error = WorkspaceError(provider.domain_id, "apply",
                           f"{type(exc).__name__}: {exc}"[:400])
    return {"domain_id": provider.domain_id, "status": "skipped",
            "rolled_back": True, **error.to_dict()}


def _apply_domain(bridge, provider, doc) -> dict:
    """The per-domain transaction: commit, or roll back to the pre-apply capture."""
    previous = provider.capture(bridge)
    try:
        outcome = provider.apply(bridge, doc)
        return {"domain_id": provider.domain_id, "status": "restored",
                "notes": list(outcome.notes)}
    except Exception as exc:
        return _rollback(bridge, provider, previous, exc)


def _dependency_row(provider, failed: set) -> dict | None:
    """A domain whose strict dependency was skipped restores never-half (task rule 4)."""
    blocked = sorted(d for d, kind in (provider.dependencies or {}).items()
                     if kind == "strict" and d in failed)
    if not blocked:
        return None
    error = WorkspaceError(provider.domain_id, "dependency",
                           f"strict dependency failed: {', '.join(blocked)}")
    return _skip_row(provider, error)


def _migrated_doc(provider, entry: dict, doc) -> tuple[object, str]:
    """Run the provider's migration chain when the saved schema predates this build."""
    if entry.get("schema_version") == provider.schema_version:
        return doc, ""
    return provider.migrate(doc, entry.get("schema_version"))


def _restore_one(plan: dict, provider, entry: dict, doc) -> dict:
    """Gates in order: dependency → schema → migration → semantic → transactional apply."""
    dependency_problem = _dependency_row(provider, plan["failed"])
    if dependency_problem:
        return dependency_problem
    version_problem = _version_row(provider, entry)
    if version_problem:
        return version_problem
    doc, migrated_note = _migrated_doc(provider, entry, doc)
    semantic = provider.validate(doc)
    if semantic:
        return _skip_row(provider, WorkspaceError(provider.domain_id, "semantic", semantic))
    row = _apply_domain(plan["bridge"], provider, doc)
    if migrated_note and row["status"] == "restored":
        row["migrated"] = migrated_note
    return row


def _restore_row(plan: dict, provider) -> dict:
    """One provider's row: policy row, file-gate skip, or the gated restore."""
    entry = entry_for(plan["manifest"], provider.domain_id) or {}
    if not entry or not entry.get("path"):
        return _policy_row(provider, entry)
    loaded = plan["files"].get(entry["path"])
    if isinstance(loaded, WorkspaceError):
        error = WorkspaceError(provider.domain_id, loaded.stage, loaded.cause,
                               evidence=(loaded.expected, loaded.actual))
        return _skip_row(provider, error)
    return _restore_one(plan, provider, entry, loaded)


def restore_workspace(bridge, root, selected=None) -> dict:
    """Selected/all domains, dependency order, per-domain transaction (task RESTORE 2–10)."""
    root = Path(root)
    manifest, err = read_manifest(root)
    if err:
        return {"ok": False, "error": err}
    providers, unknown = selection_providers(manifest, selected)
    if unknown:
        return {"ok": False, "error": f"unknown domain(s): {', '.join(unknown)}"}
    providers = expand_strict(providers)
    if not providers:
        return {"ok": False, "error": "no restorable domains selected"}
    backup = backup_live(bridge, providers)
    plan = {"bridge": bridge, "manifest": manifest,
            "files": load_files(root, manifest, providers), "failed": set()}
    rows = []
    for provider in providers:
        row = _restore_row(plan, provider)
        rows.append(row)
        if row["status"] != "restored":
            plan["failed"].add(provider.domain_id)
    report = _finish(bridge, root, rows, backup)
    log_message(bridge, f"♻️ Workspace restore from {root.name}: {report['result']} — "
                 f"{len(report['restored'])} restored, {len(report['skipped'])} skipped",
         "success" if report["result"] == "success" else
         ("warn" if report["result"] == "success_with_warnings" else "error"))
    return {"ok": report["result"] != "failed", **report}


def _finish(bridge, root: Path, rows: list, backup: str) -> dict:
    """Reconcile restored domains, then write the restore-report into the folder."""
    restored_ids = [r["domain_id"] for r in rows if r["status"] == "restored"]
    migrated = [{"domain_id": r["domain_id"], "note": r["migrated"]}
                for r in rows if r.get("migrated")]
    outcomes = {"restored": restored_ids,
                "skipped": [r for r in rows if r["status"] != "restored"],
                "migrated": migrated,
                "reconciled": _reconcile_all(bridge, restored_ids)}
    report = reports.restore_report(workspace=str(root), outcomes=outcomes,
                                    backup=backup)
    _write_restore_report(root, report)
    record_restore(bridge, str(root), report["result"])
    return report


def _reconcile_all(bridge, restored_ids: list) -> list:
    """Derived/live recomputation after restore (task RESTORE 8) — failures are notes."""
    notes = []
    for domain_id in restored_ids:
        provider = get(domain_id)
        try:
            notes.extend(provider.reconcile(bridge))
        except Exception as exc:
            notes.append(f"{domain_id}: reconcile failed: {type(exc).__name__}: {exc}")
    return notes


def _write_restore_report(root: Path, report: dict) -> None:
    """Into `<root>/reports/`; a read-only folder gets a sibling file instead."""
    try:
        fsio.write_bytes(root, "reports/restore-report.json", canonical_bytes(report))
        return
    except OSError:
        pass
    try:
        sibling = root.with_name(root.name + ".restore-report.json")
        sibling.write_bytes(canonical_bytes(report))
        report["report_note"] = f"folder read-only — report written beside it: {sibling.name}"
    except OSError:
        report["report_note"] = "report could not be written to disk (in-UI copy only)"
