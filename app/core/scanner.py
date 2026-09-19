from pathlib import Path
from typing import List, Set
import os
from .naming import is_ai_generated_filename
from ..utils.hashing import fingerprint_from_path_stat

SUPPORTED_EXTS_DEFAULT = {".png", ".jpg", ".jpeg", ".webp"}

def scan_folder(
    root_path: Path,
    supported_exts: Set[str] | None = None,
    ignore_ai_suffix: bool = True,
    recursive: bool = True,
) -> List[dict]:
    """
    Recursively scan subfolders for supported images.
    Preserve original folder structure; do not move source files.
    Returns list of dicts with file info.
    """
    root_path = Path(root_path)
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Root path does not exist or not a directory: {root_path}")
    exts = _normalize_exts(supported_exts)
    results = [_scan_entry(p, root_path, exts, ignore_ai_suffix)
               for p in _scan_iterator(root_path, recursive)]
    results = [r for r in results if r is not None]
    # Sort by relative path for determinism
    results.sort(key=lambda x: x["relative_path"])
    return results


def _normalize_exts(supported_exts: Set[str] | None) -> Set[str]:
    """Lower-cased, dot-prefixed extension set (defaults when None)."""
    if supported_exts is None:
        return SUPPORTED_EXTS_DEFAULT
    normalized = set()
    for ext in supported_exts:
        e = ext.lower()
        if not e.startswith("."):
            e = f".{e}"
        normalized.add(e)
    return normalized


def _scan_iterator(root_path: Path, recursive: bool):
    """All paths under root (recursive rglob or flat glob)."""
    if recursive:
        return root_path.rglob("*")
    return root_path.glob("*")


def _scan_entry(p: Path, root_path: Path, exts: Set[str], ignore_ai_suffix: bool):
    """Scan dict for one file, or None when skipped (wrong type/AI/unreadable)."""
    if not p.is_file():
        return None
    ext = p.suffix.lower()
    if ext not in exts:
        return None
    if ignore_ai_suffix and is_ai_generated_filename(p):
        return None
    try:
        return _scan_dict(p, root_path, ext)
    except Exception as e:
        # Skip unreadable files but log
        print(f"Warning: cannot stat {p}: {e}")
        return None


def _scan_dict(p: Path, root_path: Path, ext: str) -> dict:
    """File info dict (paths, size, mtime, fingerprint)."""
    stat = p.stat()
    size = stat.st_size
    mtime = stat.st_mtime
    rel = p.relative_to(root_path).as_posix()
    fp = fingerprint_from_path_stat(rel, size, mtime)
    return {
        "absolute_path": str(p.resolve()),
        "relative_path": rel,
        "filename": p.name,
        "base_name": p.stem,
        "extension": ext,
        "size": size,
        "mtime": mtime,
        "fingerprint": fp,
        "id": fp,  # use fingerprint as id initially
    }


def detect_changes(previous_items: List[dict], current_items: List[dict]) -> dict:
    """
    Detect files added, removed, renamed, or changed after initial scan.
    Returns dict with added, removed, changed, unchanged lists.
    """
    prev_by_rel = _index_by_rel(previous_items)
    curr_by_rel = _index_by_rel(current_items)
    added, changed, unchanged = _classify_current(prev_by_rel, curr_by_rel)
    removed = _removed_entries(prev_by_rel, curr_by_rel)
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }


def _entry_changed(prev: dict, curr: dict) -> bool:
    """True when size or mtime differs between scans."""
    return curr["size"] != prev["size"] or curr["mtime"] != prev["mtime"]


def _index_by_rel(items: List[dict]) -> dict:
    """Scan dicts indexed by relative_path."""
    return {item["relative_path"]: item for item in items}


def _classify_current(prev_by_rel: dict, curr_by_rel: dict) -> tuple:
    """(added, changed, unchanged) for current-scan entries vs previous."""
    added, changed, unchanged = [], [], []
    for rel, curr in curr_by_rel.items():
        prev = prev_by_rel.get(rel)
        if not prev:
            added.append(curr)
        elif _entry_changed(prev, curr):
            changed.append({"old": prev, "new": curr})
        else:
            unchanged.append(curr)
    return added, changed, unchanged


def _removed_entries(prev_by_rel: dict, curr_by_rel: dict) -> list:
    """Previous entries no longer present in the current scan."""
    return [prev for rel, prev in prev_by_rel.items() if rel not in curr_by_rel]
