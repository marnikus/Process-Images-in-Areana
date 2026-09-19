"""Scanner — C5 refactor with ScanSpec param object and predicate table."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

from .naming import is_ai_generated_filename
from ..utils.hashing import fingerprint_from_path_stat

SUPPORTED_EXTS_DEFAULT = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class ScanSpec:
    """Param object for scan_folder (C5)."""
    supported_exts: Set[str] | None = None
    ignore_ai_suffix: bool = True
    recursive: bool = True


def _normalize_exts(exts: Set[str] | None) -> Set[str]:
    if exts is None:
        return SUPPORTED_EXTS_DEFAULT
    normalized = set()
    for ext in exts:
        e = ext.lower()
        if not e.startswith("."):
            e = f".{e}"
        normalized.add(e)
    return normalized


def _should_include(path: Path, exts: Set[str], ignore_ai: bool) -> bool:
    if not path.is_file():
        return False
    ext = path.suffix.lower()
    if ext not in exts:
        return False
    if ignore_ai and is_ai_generated_filename(path):
        return False
    return True


def _build_item(root_path: Path, path: Path) -> dict | None:
    try:
        stat = path.stat()
        size = stat.st_size
        mtime = stat.st_mtime
        rel = path.relative_to(root_path).as_posix()
        fp = fingerprint_from_path_stat(rel, size, mtime)
        return {
            "absolute_path": str(path.resolve()),
            "relative_path": rel,
            "filename": path.name,
            "base_name": path.stem,
            "extension": path.suffix.lower(),
            "size": size,
            "mtime": mtime,
            "fingerprint": fp,
            "id": fp,
        }
    except Exception as e:
        print(f"Warning: cannot stat {path}: {e}")
        return None


def _get_iterator(root_path: Path, recursive: bool):
    return root_path.rglob("*") if recursive else root_path.glob("*")


def scan_folder(root_path: Path, spec: ScanSpec | None = None) -> List[dict]:
    if spec is None:
        spec = ScanSpec()
    root_path = Path(root_path)
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Root path does not exist or not a directory: {root_path}")

    supported = _normalize_exts(spec.supported_exts)
    results: List[dict] = []

    for p in _get_iterator(root_path, spec.recursive):
        if not _should_include(p, supported, spec.ignore_ai_suffix):
            continue
        item = _build_item(root_path, p)
        if item:
            results.append(item)

    results.sort(key=lambda x: x["relative_path"])
    return results


def scan_folder_legacy(
    root_path: Path,
    supported_exts: Set[str] | None = None,
    ignore_ai_suffix: bool = True,
    recursive: bool = True,
) -> List[dict]:
    spec = ScanSpec(
        supported_exts=supported_exts,
        ignore_ai_suffix=ignore_ai_suffix,
        recursive=recursive,
    )
    return scan_folder(root_path, spec)


def detect_changes(previous_items: List[dict], current_items: List[dict]) -> dict:
    prev_by_rel = {item["relative_path"]: item for item in previous_items}
    curr_by_rel = {item["relative_path"]: item for item in current_items}

    added = []
    removed = []
    changed = []
    unchanged = []

    for rel, curr in curr_by_rel.items():
        prev = prev_by_rel.get(rel)
        if not prev:
            added.append(curr)
        elif curr["size"] != prev["size"] or curr["mtime"] != prev["mtime"]:
            changed.append({"old": prev, "new": curr})
        else:
            unchanged.append(curr)

    for rel, prev in prev_by_rel.items():
        if rel not in curr_by_rel:
            removed.append(prev)

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }
