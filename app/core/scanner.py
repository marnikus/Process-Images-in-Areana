from pathlib import Path
from typing import List, Set
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

    if supported_exts is None:
        supported_exts = SUPPORTED_EXTS_DEFAULT
    else:
        # Normalize to lower with dot
        normalized = set()
        for ext in supported_exts:
            e = ext.lower()
            if not e.startswith("."):
                e = f".{e}"
            normalized.add(e)
        supported_exts = normalized

    results = []
    if recursive:
        iterator = root_path.rglob("*")
    else:
        iterator = root_path.glob("*")

    for p in iterator:
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in supported_exts:
            continue
        if ignore_ai_suffix and is_ai_generated_filename(p):
            continue
        try:
            stat = p.stat()
            size = stat.st_size
            mtime = stat.st_mtime
            rel = p.relative_to(root_path).as_posix()
            fp = fingerprint_from_path_stat(rel, size, mtime)
            results.append({
                "absolute_path": str(p.resolve()),
                "relative_path": rel,
                "filename": p.name,
                "base_name": p.stem,
                "extension": ext,
                "size": size,
                "mtime": mtime,
                "fingerprint": fp,
                "id": fp,  # use fingerprint as id initially
            })
        except Exception as e:
            # Skip unreadable files but log
            print(f"Warning: cannot stat {p}: {e}")
            continue

    # Sort by relative path for determinism
    results.sort(key=lambda x: x["relative_path"])
    return results

def detect_changes(previous_items: List[dict], current_items: List[dict]) -> dict:
    """
    Detect files added, removed, renamed, or changed after initial scan.
    Returns dict with added, removed, changed, unchanged lists.
    """
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
        else:
            # Check if size or mtime changed
            if curr["size"] != prev["size"] or curr["mtime"] != prev["mtime"]:
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
