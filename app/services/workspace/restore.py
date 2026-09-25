"""Workspace restore — the manifest-only PREVIEW (read-only; design §C.6).

Before any mutation the user sees exactly what a restore would do: per-domain
status (ok / size_mismatch / missing / excluded / not_in_manifest) from the
manifest, plus path-remap notes. The mutating side — selection, strict-dependency
expansion, recovery backup, file gates, transactions, reconcile, report — lives
in `apply.py`. No Qt.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.persistence.workspace.manifest import entry_for, read_manifest
from . import reports
from .registry import restore_order

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
    domains = [_preview_row(root, manifest, d)
               for d in restore_order(set(manifest.get("domains", {})))]
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
