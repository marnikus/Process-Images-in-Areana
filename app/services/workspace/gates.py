"""Workspace file gates — safe path → size → sha-256 → JSON parse (design §F).

Read-only: turns one snapshot file into its parsed doc or a precise
`WorkspaceError` row; never touches live state (the mutating side is
`apply.py`). Imports: persistence.workspace only — no Qt, no app.ui.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import file_sha, safe_rel_path
from app.persistence.workspace.manifest import entry_for


def load_files(root: Path, manifest: dict, providers: list) -> dict:
    """rel → parsed doc or WorkspaceError — checksum + parse gates once per file."""
    docs: dict = {}
    for provider in providers:
        entry = entry_for(manifest, provider.domain_id) or {}
        rel = entry.get("path")
        if not rel or rel in docs:
            continue
        docs[rel] = load_one(root, entry, rel)
    return docs


def load_one(root: Path, entry: dict, rel: str):
    """Parsed doc or WorkspaceError; an unreadable file is a `parse` row, never a raise."""
    try:
        return _gated(root, entry, rel)
    except OSError as exc:
        return WorkspaceError(entry_owner(entry), "parse", f"cannot read file: {exc}")


def _gated(root: Path, entry: dict, rel: str):
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
    except ValueError as exc:
        return WorkspaceError(entry_owner(entry), "parse", f"invalid JSON: {exc}")


def entry_owner(entry: dict) -> str:
    """Best-effort owner name for a file-level problem row."""
    return entry.get("display_name", "workspace file")
