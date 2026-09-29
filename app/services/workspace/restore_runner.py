"""Workspace restore runner — preflight, backup, loop, report, reconcile.

Split from apply.py (S5): orchestrates a full restore run, delegates
selection to `selection.py` and per-domain work to `transaction.py`.
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.workspace import fsio
from app.persistence.workspace.integrity import canonical_bytes
from app.persistence.workspace.manifest import read_manifest
from . import reports
from .gates import load_files
from .meta import live_run_error, log_message
from .recover import BackupResult, backup_live
from .registry import get
from .selection import expand_strict, selection_providers
from .snapshot_index import record_restore
from .transaction import _restore_row


def _preflight(bridge, root: Path, selected) -> tuple:
    """(manifest, providers, None) or (None, None, refusal) — nothing touched yet."""
    busy = live_run_error(bridge)
    if busy:
        return None, None, busy
    manifest_read = read_manifest(root)
    # ManifestRead is iterable as (manifest, error) for compat
    manifest, err = (manifest_read.manifest, manifest_read.error) \
        if hasattr(manifest_read, "manifest") else manifest_read
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
    """Selected/all domains, dependency order, per-domain transaction."""
    root = Path(root)
    manifest, providers, refusal = _preflight(bridge, root, selected)
    if refusal:
        return {"ok": False, "error": refusal}
    backup_result = backup_live(bridge, providers)
    if isinstance(backup_result, BackupResult):
        if backup_result.refusal:
            return {"ok": False, "error": backup_result.refusal}
        backup_path = backup_result.path
    else:  # tuple compat
        backup_path, backup_refusal = backup_result
        if backup_refusal:
            return {"ok": False, "error": backup_refusal}

    # typed context (defined in apply.py for backward compat, import here to avoid cycle)
    from .apply import RestoreRunContext
    ctx = RestoreRunContext(
        bridge=bridge, manifest=manifest,
        files=load_files(root, manifest, providers), failed=set())
    rows = []
    for provider in providers:
        row = _restore_row(ctx, provider)
        rows.append(row)
        if row["status"] != "restored":
            ctx.failed.add(provider.domain_id)
    report = _finish(bridge, root, rows, backup_path)
    _log_result(bridge, root, report)
    return {"ok": report["result"] != "failed", **report}


_RESULT_LEVEL = {"success": "success", "success_with_warnings": "warn"}


def _log_result(bridge, root: Path, report: dict) -> None:
    """One app-log line per restore; anything but success/warnings logs as error."""
    log_message(bridge,
                f"♻️ Workspace restore from {root.name}: {report['result']} — "
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
    note = fsio.write_report(root, "reports/restore-report.json",
                             canonical_bytes(report))
    if note:
        report["report_note"] = note
    record_restore(bridge, str(root), report["result"])
    return report


def _reconcile_all(bridge, restored_ids: list) -> list:
    """Derived/live recomputation after restore — failures are notes."""
    notes = []
    for domain_id in restored_ids:
        provider = get(domain_id)
        try:
            notes.extend(provider.reconcile(bridge))
        except Exception as exc:
            notes.append(f"{domain_id}: reconcile failed: {type(exc).__name__}: {exc}")
    return notes
