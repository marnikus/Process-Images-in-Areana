"""Workspace manifest — build, read, validate (workspace_format 1).

manifest.json is the commit marker (its presence defines a published
snapshot) and the only ownership registry: a domain is restored through
its manifest entry, never by filename guessing. Imports: stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path

from .integrity import canonical_bytes

FORMAT_NAME = "arena-workspace"
WORKSPACE_FORMAT = 1
MIN_WORKSPACE_FORMAT = 1


def build_manifest(*, header: dict, app_meta: dict, compat: dict,
                   domains: dict) -> dict:
    """The one manifest builder (every registered domain appears — included or excluded).

    `header` bundles snapshot_id/name/description/created_utc and the optional
    snapshot_kind/parent_id — one identity dict instead of six parameters.
    """
    created = header.get("created_utc", "")
    return {
        "format": FORMAT_NAME,
        "workspace_format": WORKSPACE_FORMAT,
        "snapshot_id": header.get("snapshot_id", ""),
        "parent_snapshot_id": header.get("parent_id"),
        "name": str(header.get("name", "")),
        "description": str(header.get("description") or ""),
        "snapshot_kind": header.get("snapshot_kind", "full"),
        "created_utc": created,
        "updated_utc": created,
        "app": dict(app_meta),
        "compat": dict(compat),
        "domains": domains,
    }


def check_format(manifest: dict) -> str | None:
    """Refusal reason for a foreign/future manifest, or None when loadable."""
    if not isinstance(manifest, dict):
        return "manifest is not a JSON object"
    if manifest.get("format") != FORMAT_NAME:
        return f"not a {FORMAT_NAME} folder (format={manifest.get('format')!r})"
    version = manifest.get("workspace_format")
    if isinstance(version, bool) or not isinstance(version, int):
        return f"workspace_format is not a number: {version!r}"
    if version < MIN_WORKSPACE_FORMAT:
        return f"workspace_format {version} is older than the supported minimum {MIN_WORKSPACE_FORMAT}"
    if version > WORKSPACE_FORMAT:
        return (f"saved by a newer app (workspace_format {version} > "
                f"supported {WORKSPACE_FORMAT}) — update the app")
    if not isinstance(manifest.get("domains"), dict) or not manifest["domains"]:
        return "manifest lists no domains"
    return None


def parse_manifest(raw) -> tuple[dict | None, str | None]:
    """Validate one parsed manifest; (manifest, None) or (None, reason)."""
    err = check_format(raw) if isinstance(raw, dict) else "manifest is not a JSON object"
    return (None, err) if err else (raw, None)


def read_manifest(root: Path) -> tuple[dict | None, str | None]:
    """Read + validate `<root>/manifest.json` (the only entry point for a folder)."""
    path = Path(root) / "manifest.json"
    if not path.exists():
        return None, "manifest.json missing — this folder is not a committed workspace snapshot"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"manifest.json unreadable: {exc}"
    return parse_manifest(raw)


def entry_for(manifest: dict, domain_id: str) -> dict | None:
    entry = manifest.get("domains", {}).get(domain_id)
    return entry if isinstance(entry, dict) else None


def domain_for_file(manifest: dict, rel_path: str) -> list[str]:
    """Domain ids owning one workspace file (manifest lookup, never name-guessing)."""
    hits = []
    for domain_id, entry in manifest.get("domains", {}).items():
        if isinstance(entry, dict) and entry.get("path") == rel_path:
            hits.append(domain_id)
    return hits


def manifest_bytes(manifest: dict) -> bytes:
    """Canonical manifest serialisation (written last, same shape everywhere)."""
    return canonical_bytes(manifest)
