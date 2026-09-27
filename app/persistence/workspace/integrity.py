"""Workspace integrity — checksums, canonical bytes, safe relative paths.

Capture serialises every domain doc deterministically (sorted keys, fixed
indent) so checksums and reports stay byte-stable across saves of identical
state; restore accepts any byte layout that parses to the same validated
doc (design §C.3). Imports: stdlib only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


def canonical_bytes(doc) -> bytes:
    """The one serialisation for checksums and written files (stable across saves)."""
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bytes_entry(rel_path: str, data: bytes) -> dict:
    """`{path, bytes, sha256}` for one serialised payload (the one entry builder)."""
    return {"path": rel_path, "bytes": len(data), "sha256": sha256_bytes(data)}


def doc_entry(rel_path: str, doc) -> dict:
    """`{path, bytes, sha256}` for one canonical serialisation."""
    return bytes_entry(rel_path, canonical_bytes(doc))


def drive_like(text: str) -> bool:
    """Windows drive prefix (`C:/…`) — absolute on Windows, not to PurePosixPath."""
    head = text.split("/", 1)[0]
    return len(head) == 2 and head[1] == ":"


def safe_rel_path(rel) -> str:
    """Normalised relative path inside the workspace, or '' when unsafe.

    Rejects empty/absolute/drive/`..` paths; returns a POSIX-relative path
    safe to join under the workspace root (never escapes it).
    """
    if not isinstance(rel, str) or not rel.strip():
        return ""
    pure = PurePosixPath(rel.strip().replace("\\", "/"))
    if pure.is_absolute() or drive_like(rel) or ".." in pure.parts:
        return ""
    cleaned = "/".join(p for p in pure.parts if p not in ("", "."))
    if not cleaned or cleaned.startswith("/"):
        return ""
    return cleaned


def file_sha(path: Path) -> str:
    """Checksum of an on-disk file (streamed; small JSON files)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
