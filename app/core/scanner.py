"""Scanner — C5 refactor with ScanSpec param object and predicate table.

B13 (2026-10-09): one directory walk also yields `existing_output` per
source — the best `<base>_AI[_n].<ext>` sibling already on disk — so a
discovered image whose output exists enters the queue as `completed`
(I-46). Outputs are read, never written or removed here (RULE 14).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

from .naming import is_ai_generated_filename, parse_ai_output
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


# ideal-size: 22 lines reason=one scan-item dict literal, one key per line (the queue item contract, RULE 18.5)
def _build_item(root_path: Path, path: Path, existing_output: Path | None = None) -> dict | None:
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
            "existing_output": str(existing_output) if existing_output else None,
        }
    except Exception as e:
        print(f"Warning: cannot stat {path}: {e}")
        return None


def _get_iterator(root_path: Path, recursive: bool):
    return root_path.rglob("*") if recursive else root_path.glob("*")


def _checked_root(root_path: Path) -> Path:
    """Existing directory, or ValueError — the scan never guesses a root."""
    root_path = Path(root_path)
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Root path does not exist or not a directory: {root_path}")
    return root_path


def _output_rank(counter: int | None) -> tuple:
    """Exact `_AI` before counters; among counters the highest (= the last save)."""
    return (0, 0) if counter is None else (1, -counter)


def _outputs_by_source(images: List[Path]) -> Dict[Path, Path]:
    """`<dir>/<base>` → its best existing `_AI` sibling, any supported extension (I-46)."""
    best: Dict[Path, tuple] = {}
    for p in images:
        parsed = parse_ai_output(p.stem)  # the one family definition (naming, RULE 10)
        if parsed is None:
            continue
        base, counter = parsed
        key, rank = p.parent / base, _output_rank(counter)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, p)
    return {key: path for key, (_, path) in best.items()}


def scan_folder(root_path: Path, spec: ScanSpec | None = None) -> List[dict]:
    """Source dicts under root (RULE 6 filters) with `existing_output` per source."""
    if spec is None:
        spec = ScanSpec()
    root_path = _checked_root(root_path)
    exts = _normalize_exts(spec.supported_exts)
    # One walk: every supported file, sources and `_AI` outputs alike.
    images = [p for p in _get_iterator(root_path, spec.recursive) if _should_include(p, exts, False)]
    outputs = _outputs_by_source(images)
    sources = [p for p in images if not (spec.ignore_ai_suffix and is_ai_generated_filename(p))]
    items = [_build_item(root_path, p, outputs.get(p.parent / p.stem)) for p in sources]
    results = [item for item in items if item]
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
