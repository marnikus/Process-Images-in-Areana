"""Workspace restore — the whole MUTATING side (design §C.6/§F).

Selection + strict-dependency expansion, recovery backup of live files,
the file gates (safe-path → checksum → parse), the per-domain transaction
(dependency → schema → migration → semantic → apply with rollback to the
pre-apply capture), derived-state reconcile, and the restore-report written
into the workspace folder. The read-only preview lives in `restore.py`; the file gates in `gates.py`.
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.workspace import fsio
from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import canonical_bytes
from app.persistence.workspace.manifest import entry_for, read_manifest
from . import reports
from .gates import load_files
from .meta import live_run_error, log_message
from .recover import backup_live
from .registry import get, restore_order
from .runs import RestoreRun
from .snapshot_index import record_restore


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


def _skip_row(provider, error: WorkspaceError) -> dict:
    return {"domain_id": provider.domain_id, "status": "skipped", **error.to_dict()}


def _guarded(provider, stage: str, call, *args) -> tuple:
    """(value, None) or (None, skip row): a provider crash is its own domain's row (§F)."""
    try:
        return call(*args), None
    except Exception as exc:
        error = WorkspaceError(provider.domain_id, stage, f"{type(exc).__name__}: {exc}"[:400])
        return None, _skip_row(provider, error)


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
    advice = provider.restore_advice
    if advice:
        row["recommended_action"] = advice
    return row


def _rollback(bridge, provider, previous, exc: Exception) -> dict:
    """Roll back to the pre-apply capture; an impossible rollback is `damaged`, loud.

    `rolled_back` says whether a rollback actually ran (no usable capture → False).
    """
    can_roll_back = bool(previous.ok and previous.doc is not None and not previous.excluded)
    if can_roll_back:
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
            "rolled_back": can_roll_back, **error.to_dict()}


def _apply_domain(bridge, provider, doc) -> dict:
    """The per-domain transaction: commit, or roll back to the pre-apply capture.

    No readable pre-apply capture → no rollback point → the domain is not applied.
    """
    previous, problem = _guarded(provider, "apply", provider.capture, bridge)
    if problem:
        problem["cause"] = f"pre-apply values unreadable — not applied: {problem['cause']}"
        return problem
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


def _checked_doc(provider, entry: dict, doc) -> tuple:
    """(doc, migrated_note, None) or (None, "", skip row): migration, then semantic gate."""
    migrated, problem = _guarded(provider, "migration", _migrated_doc, provider, entry, doc)
    if problem:
        return None, "", problem
    doc, note = migrated
    semantic, problem = _guarded(provider, "semantic", provider.validate, doc)
    if semantic and not problem:
        problem = _skip_row(provider, WorkspaceError(provider.domain_id, "semantic", semantic))
    return (None, "", problem) if problem else (doc, note, None)


def _restore_one(run: RestoreRun, provider, entry: dict, doc) -> dict:
    """Gates in order: dependency → schema → migration → semantic → transactional apply."""
    problem = _dependency_row(provider, run.failed) or _version_row(provider, entry)
    if problem:
        return problem
    doc, migrated_note, problem = _checked_doc(provider, entry, doc)
    if problem:
        return problem
    row = _apply_domain(run.bridge, provider, doc)
    if migrated_note and row["status"] == "restored":
        row["migrated"] = migrated_note
    return row


def _restore_row(run: RestoreRun, provider) -> dict:
    """One provider's row: policy row, file-gate skip, or the gated restore."""
    entry = entry_for(run.manifest, provider.domain_id) or {}
    if not entry or not entry.get("path"):
        return _policy_row(provider, entry)
    loaded = run.files.get(entry["path"])
    if isinstance(loaded, WorkspaceError):
        error = WorkspaceError(provider.domain_id, loaded.stage, loaded.cause,
                               evidence=(loaded.expected, loaded.actual))
        return _skip_row(provider, error)
    return _restore_one(run, provider, entry, loaded)


def _preflight(bridge, root: Path, selected) -> tuple:
    """(manifest, providers, None) or (None, None, refusal) — nothing touched yet."""
    busy = live_run_error(bridge)
    if busy:
        return None, None, busy
    manifest, err = read_manifest(root)
    if err:
        return None, None, err
    providers, unknown = selection_providers(manifest, selected)
    if unknown:
        return None, None, f"unknown domain(s): {', '.join(unknown)}"
    providers = expand_strict(providers)
    if not providers:
        return None, None, "no restorable domains selected"
    return manifest, providers, None


def restore_workspace(bridge, root, selected=None) -> dict:
    """Selected/all domains, dependency order, per-domain transaction (task RESTORE 2–10)."""
    root = Path(root)
    manifest, providers, refusal = _preflight(bridge, root, selected)
    if refusal:
        return {"ok": False, "error": refusal}
    backup, backup_refusal = backup_live(bridge, providers)
    if backup_refusal:
        return {"ok": False, "error": backup_refusal}
    run = RestoreRun(bridge=bridge, manifest=manifest,
                     files=load_files(root, manifest, providers), failed=set())
    rows = []
    for provider in providers:
        row = _restore_row(run, provider)
        rows.append(row)
        if row["status"] != "restored":
            run.failed.add(provider.domain_id)
    report = _finish(bridge, root, rows, backup)
    _log_result(bridge, root, report)
    return {"ok": report["result"] != "failed", **report}


_RESULT_LEVEL = {"success": "success", "success_with_warnings": "warn"}


def _log_result(bridge, root: Path, report: dict) -> None:
    """One app-log line per restore; anything but success/warnings logs as error."""
    log_message(bridge, f"♻️ Workspace restore from {root.name}: {report['result']} — "
                        f"{len(report['restored'])} restored, {len(report['skipped'])} skipped",
                _RESULT_LEVEL.get(report["result"], "error"))


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
    note = fsio.write_report(root, "reports/restore-report.json", canonical_bytes(report))
    if note:
        report["report_note"] = note
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
