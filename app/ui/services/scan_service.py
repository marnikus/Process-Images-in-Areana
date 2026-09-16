"""Scan Service — pure wrapper around scanner.py extracted from bridge.py (Phase 2).

Goals:
- No Qt, no signals — pure function root_path → scanned list.
- Testable with tmp_path, no QApplication.
- RULE 18: file 150-300 LOC ideal, current ~110 LOC.
- RULE 16: func LOC ≤30, CC ≤10, nesting ≤4, params ≤4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set


def scan_folder_pure(
    root_path: Path, supported_types: Set[str] | None = None, ignore_ai_suffix: bool = True
) -> List[Dict]:
    """Pure scan wrapper — delegates to core.scanner.scan_folder but no Qt."""
    from ...core.scanner import scan_folder

    if supported_types is None:
        supported_types = {".png", ".jpg", ".jpeg", ".webp"}
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        return []
    try:
        return scan_folder(root, supported_types, ignore_ai_suffix)
    except Exception:
        return []


def merge_scan_results(
    existing_by_rel: Dict[str, Dict], scanned: List[Dict]
) -> Dict[str, int]:
    """Pure merge logic — given existing dict and scanned list, returns counts.

    Does not mutate FS, only computes what would be added/updated.
    """
    added = 0
    updated = 0
    for s in scanned:
        rel = s.get("relative_path")
        if not rel:
            continue
        if rel not in existing_by_rel:
            added += 1
        else:
            updated += 1
    return {"added": added, "updated": updated, "total": len(scanned)}


def should_ignore_file(filename: str, ignore_ai_suffix: bool = True) -> bool:
    """Pure ignore decision — same as scanner logic."""
    if not ignore_ai_suffix:
        return False
    name_lower = filename.lower()
    # Ignore *_AI.ext
    if "_ai." in name_lower:
        # Check if _ai is before extension
        stem = Path(filename).stem.lower()
        if stem.endswith("_ai"):
            return True
    return False
