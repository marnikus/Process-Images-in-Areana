"""Workspace restore transaction — per-domain gates and rollback.

Split from apply.py (S5): dependency → schema → migration → semantic →
transactional apply with rollback to pre-apply capture. No backup, no
report writing, only one provider at a time.
"""

from __future__ import annotations

from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.manifest import entry_for
from .registry import get


def _skip_row(provider, error: WorkspaceError) -> dict:
    return {"domain_id": provider.domain_id, "status": "skipped", **error.to_dict()}


def _guarded(provider, stage: str, call, *args) -> tuple:
    """(value, None) or (None, skip row): provider crash is its own row."""
    try:
        return call(*args), None
    except Exception as exc:
        error = WorkspaceError(provider.domain_id, stage,
                               f"{type(exc).__name__}: {exc}"[:400])
        return None, _skip_row(provider, error)


def _version_row(provider, entry: dict) -> dict | None:
    """Schema gate: unsupported future versions are refused."""
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
    """Domain with no file (secret / opt-out) — never applied, explained."""
    cause = (entry.get("capture", {}) or {}).get("excluded_reason",
                                                 "policy-excluded domain")
    row = {"domain_id": provider.domain_id, "status": "skipped",
           "stage": "apply", "policy": True, "cause": cause}
    advice = getattr(provider, "restore_advice", "")
    if advice:
        row["recommended_action"] = advice
    return row


def _rollback(bridge, provider, previous, exc: Exception) -> dict:
    """Roll back to pre-apply capture; impossible rollback is `damaged`."""
    can_roll_back = bool(previous.ok and previous.doc is not None
                         and not previous.excluded)
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
    """Per-domain transaction: commit, or roll back to pre-apply capture."""
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
    """Domain whose strict dependency was skipped → never-half."""
    blocked = sorted(d for d, kind in (provider.dependencies or {}).items()
                     if kind == "strict" and d in failed)
    if not blocked:
        return None
    error = WorkspaceError(provider.domain_id, "dependency",
                           f"strict dependency failed: {', '.join(blocked)}")
    return _skip_row(provider, error)


def _migrated_doc(provider, entry: dict, doc) -> tuple[object, str]:
    """Run migration chain when saved schema predates this build."""
    if entry.get("schema_version") == provider.schema_version:
        return doc, ""
    return provider.migrate(doc, entry.get("schema_version"))


def _checked_doc(provider, entry: dict, doc) -> tuple:
    """(doc, migrated_note, None) or (None, "", skip row)."""
    migrated, problem = _guarded(provider, "migration",
                                 _migrated_doc, provider, entry, doc)
    if problem:
        return None, "", problem
    doc, note = migrated
    semantic, problem = _guarded(provider, "semantic", provider.validate, doc)
    if semantic and not problem:
        problem = _skip_row(provider,
                            WorkspaceError(provider.domain_id, "semantic", semantic))
    return (None, "", problem) if problem else (doc, note, None)


def _restore_one(ctx, provider, entry: dict, doc) -> dict:
    """Gates in order: dependency → schema → migration → semantic → apply."""
    problem = _dependency_row(provider, ctx.failed) or _version_row(provider, entry)
    if problem:
        return problem
    doc, migrated_note, problem = _checked_doc(provider, entry, doc)
    if problem:
        return problem
    row = _apply_domain(ctx.bridge, provider, doc)
    if migrated_note and row["status"] == "restored":
        row["migrated"] = migrated_note
    return row


def _restore_row(ctx, provider) -> dict:
    """One provider's row: policy row, file-gate skip, or gated restore."""
    entry = entry_for(ctx.manifest, provider.domain_id) or {}
    if not entry or not entry.get("path"):
        return _policy_row(provider, entry)
    loaded = ctx.files.get(entry["path"])
    if isinstance(loaded, WorkspaceError):
        error = WorkspaceError(provider.domain_id, loaded.stage, loaded.cause,
                               evidence=(loaded.expected, loaded.actual))
        return _skip_row(provider, error)
    return _restore_one(ctx, provider, entry, loaded)
