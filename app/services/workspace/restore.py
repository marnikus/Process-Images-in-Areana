"""Workspace restore — the PREVIEW (read-only; design §C.6).

Before any mutation the user sees exactly what a restore would do: per-domain
status, plus path-remap notes. The statuses come from the manifest, the
restore's own file gates (`gates.load_files`) and each provider's `validate` /
`supported_migrations` — the same gates the mutating side runs, so a row says
`ok` only when the restore would really restore that domain. The mutating
side — selection, strict-dependency expansion, recovery backup, transactions,
reconcile, report — lives in `apply.py`. No Qt.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import resolve_inside
from app.persistence.workspace.manifest import entry_for, read_manifest
from . import reports
from .gates import load_files
from .registry import get, restore_order


def _row_head(entry: dict, domain_id: str) -> dict:
    """The identity columns every preview row carries, whatever its status."""
    return {"domain_id": domain_id, "display_name": entry.get("display_name", domain_id),
            "required": entry.get("required", False),
            "sensitivity": entry.get("sensitivity", "public"),
            "dependencies": entry.get("dependencies", {})}


def _file_status(row: dict, entry: dict, path: Path) -> dict:
    """ok / size_mismatch for a domain file that exists on disk."""
    actual = path.stat().st_size
    row.update(file=entry["path"], bytes=entry.get("bytes"),
               schema_version=entry.get("schema_version"))
    if actual != entry.get("bytes"):
        row.update(status="size_mismatch", note=f"on disk {actual} bytes")
    else:
        row.update(status="ok")
    return row


def _gate_note(row: dict, provider, doc, entry: dict) -> None:
    """Mark the row with the status the RESTORE would produce, when it would refuse.

    The checklist is the screen the user trusts most, so it must not promise a
    restore the restore then refuses. It asks the same gates the restore asks
    — the schema gate (`supported_migrations`) and `provider.validate` — and
    adds only the statuses below. Existing statuses are unchanged.
    """
    if (version := entry.get("schema_version")) not in provider.supported_migrations:
        row.update(status="unsupported_schema",
                   note=f"saved schema {version!r} is not supported by this build")
    elif problem := provider.validate(doc):
        row.update(status="invalid", note=problem)


def _gate_loaded(row: dict, loaded, entry: dict, domain_id: str) -> None:
    """The file gates already ran in `load_files` — carry their refusal across.

    A domain this build has no provider for is left at the file gates' answer:
    there is no `validate` to ask, and `apply` reports it as a skip of its own.
    """
    provider = get(domain_id)
    if provider is None:
        return
    if isinstance(loaded, WorkspaceError):
        row.update(status=loaded.stage, note=loaded.cause)
    elif loaded is not None:
        _gate_note(row, provider, loaded, entry)


def _preview_row(root: Path, manifest: dict, domain_id: str, docs: dict) -> dict:
    entry = entry_for(manifest, domain_id) or {}
    row = _row_head(entry, domain_id)
    if not entry:
        row.update(status="not_in_manifest", note="domain unknown to this snapshot")
        return row
    if entry.get("capture", {}).get("excluded") or not entry.get("path"):
        row.update(status="excluded", note=entry.get("capture", {}).get(
            "excluded_reason", "policy-excluded"))
        return row
    path = resolve_inside(root, entry["path"])
    if path is None:
        row.update(status="unsafe_path", file=entry["path"],
                   note="path escapes the snapshot folder — restore will refuse it")
        return row
    if not path.exists():
        row.update(status="missing", file=entry["path"])
        return row
    row = _file_status(row, entry, path)
    if row["status"] == "ok":
        _gate_loaded(row, docs.get(entry["path"]), entry, domain_id)
    return row


def preview_restore(root) -> dict:
    """The per-domain checklist shown before any mutation (task RESTORE 1).

    Manifest-driven, but it runs the restore's own file gates
    (`gates.load_files`) and each provider's `validate` — so a row says `ok`
    only when the restore would really restore that domain.
    """
    root = Path(root)
    manifest, err = read_manifest(root)
    if err:
        return {"ok": False, "error": err}
    order = restore_order(set(manifest.get("domains", {})))
    docs = load_files(root, manifest, [p for p in (get(d) for d in order) if p])
    domains = [_preview_row(root, manifest, d, docs) for d in order]
    return {"ok": True, **reports.preview_report(
        root=str(root), manifest=manifest, domains=domains,
        remap=_remap_notes(root, manifest))}


def _folder_root(doc) -> str:
    """The saved queue folder root, "" when the doc has none (any shape tolerated)."""
    folder = doc.get("folder") if isinstance(doc, dict) else None
    return folder.get("root_path", "") if isinstance(folder, dict) else ""


def _remap_notes(root: Path, manifest: dict) -> list:
    """Path-based resources that need user attention on this machine."""
    notes = []
    entry = entry_for(manifest, "arena_state") or {}
    path = resolve_inside(root, entry["path"]) if entry.get("path") else None
    if path:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            folder_root = _folder_root(doc)
            if folder_root and not Path(folder_root).exists():
                notes.append(f"folder root not found on this machine: {folder_root} — "
                             "restore, then re-pick the folder (queue rows keep their statuses)")
        except (OSError, ValueError):
            pass
    return notes
