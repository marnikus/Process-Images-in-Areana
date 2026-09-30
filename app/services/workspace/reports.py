"""Deterministic save/restore report builders (design §D.4).

Reports are plain dicts serialised canonically by the callers; same
inputs → byte-identical reports (tested). No Qt, no app.ui imports.
"""

from __future__ import annotations

SAVE_RESULT_OK = "success"
SAVE_RESULT_PARTIAL = "partial"
SAVE_RESULT_FAILED = "failed"
RESTORE_OK = "success"
RESTORE_WARNINGS = "success_with_warnings"
RESTORE_FAILED = "failed"


def save_report(*, timing: dict, domains: list, errors: list) -> dict:
    """The save outcome written into `reports/save-report.json`.

    A report only ever exists for a PUBLISHED snapshot: `manifest.json` is the
    commit marker, and a publish that fails returns before any report is built
    (`save._publish_failed` names the partial folder instead). So there is no
    "not published" outcome here — a saved snapshot is `success` or `partial`.
    """
    required = {d["domain_id"] for d in domains if d.get("required")}
    failed_required = [e for e in errors if e.get("domain_id") in required]
    result = SAVE_RESULT_PARTIAL if errors else SAVE_RESULT_OK
    return {**timing, "result": result,
            "domains": domains, "errors": errors, "failed_required": failed_required}


def restore_result(restored: list, skipped: list) -> str:
    """success | success_with_warnings | failed — one rule, no silent outcomes.

    A `damaged` domain (apply and rollback both failed) leaves live state unknown,
    so the whole restore is `failed` even when other domains restored.
    """
    if (not restored and skipped) or any(r.get("status") == "damaged" for r in skipped):
        return RESTORE_FAILED
    return RESTORE_WARNINGS if skipped else RESTORE_OK


def restore_report(*, workspace: str, outcomes: dict, backup: str) -> dict:
    """The restore outcome written into the workspace folder's `reports/`.

    `outcomes` bundles restored/skipped/migrated/reconciled lists.
    """
    return {"workspace": workspace, **outcomes, "backup": backup,
            "result": restore_result(outcomes.get("restored", []),
                                     outcomes.get("skipped", []))}


def preview_report(*, root: str, manifest: dict, domains: list, remap: list) -> dict:
    """Manifest-only preview — shown before any mutation (task RESTORE 1)."""
    return {
        "root": str(root),
        "snapshot_id": manifest.get("snapshot_id"),
        "name": manifest.get("name"),
        "description": manifest.get("description"),
        "snapshot_kind": manifest.get("snapshot_kind"),
        "created_utc": manifest.get("created_utc"),
        "app": manifest.get("app", {}),
        "snapshot_format": manifest.get("workspace_format"),
        "domains": domains,
        "path_remap_needed": remap,
    }
