"""Workspace restore — domain application loop, reconcile, report (design §C.6/§F).

Companion of `restore.py` (preview + gates + backup). This module owns the
per-domain transaction: strict-dependency skip, version/migration/semantic
gates, apply with per-domain rollback (the pre-apply capture re-applied —
every provider's apply is idempotent per doc), derived-state reconcile,
and the final restore-report written into the workspace folder.
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.workspace import fsio
from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import canonical_bytes
from app.persistence.workspace.manifest import entry_for, read_manifest
from . import reports
from .coordinator import _log
from .registry import get
from .restore import _backup_live, _expand_strict, _load_files, _selection_providers
from .save import record_restore


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
    providers, unknown = _selection_providers(manifest, selected)
    if unknown:
        return {"ok": False, "error": f"unknown domain(s): {', '.join(unknown)}"}
    providers = _expand_strict(providers)
    if not providers:
        return {"ok": False, "error": "no restorable domains selected"}
    backup = _backup_live(bridge, providers)
    plan = {"bridge": bridge, "manifest": manifest,
            "files": _load_files(root, manifest, providers), "failed": set()}
    rows = []
    for provider in providers:
        row = _restore_row(plan, provider)
        rows.append(row)
        if row["status"] != "restored":
            plan["failed"].add(provider.domain_id)
    report = _finish(bridge, root, rows, backup)
    _log(bridge, f"♻️ Workspace restore from {root.name}: {report['result']} — "
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
