"""Disk cleanup for _AI outputs: strip suffix / delete non-_AI.

Pure FS ops, no Qt: Drop _AI renames `photo_AI.png` back to `photo.png`
(never overwrites — collisions are skipped); Only _AI deletes every
non-_AI image. Both walk recursively, images only, hidden dirs skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator, List, Set, Tuple

from .naming import is_ai_generated_filename

_STRIP_RE = re.compile(r"_AI(_\d+)?$")


def strip_ai_name(filename: str) -> str | None:
    """Filename minus the _AI suffix (keeps _1 counters); None if N/A."""
    stem, ext = os.path.splitext(os.path.basename(filename or ""))
    m = _STRIP_RE.search(stem)
    if not m:
        return None
    return f"{stem[:m.start()]}{m.group(1) or ''}{ext}"


def _image_files(root: Path, exts: Set[str]) -> Iterator[Path]:
    """Image files under root, recursively (hidden dirs skipped)."""
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        if any(part.startswith(".") for part in p.relative_to(root).parts[:-1]):
            continue
        yield p


def strip_ai_suffixes(root, exts) -> Tuple[List[tuple], int, List[str]]:
    """Rename _AI images back; returns (pairs, skipped, errors)."""
    pairs, skipped, errors = [], 0, []
    want = {str(e).lower() for e in exts}
    for p in _image_files(Path(root), want):
        new_name = strip_ai_name(p.name)
        if not new_name:
            continue
        target = p.with_name(new_name)
        if target.exists():
            skipped += 1
            continue
        try:
            p.rename(target)
            pairs.append((p.relative_to(root).as_posix(), target.relative_to(root).as_posix()))
        except Exception as e:
            errors.append(f"{p.name}: {e}")
    return pairs, skipped, errors


def delete_non_ai_images(root, exts) -> Tuple[List[str], List[str]]:
    """Delete non-_AI images; returns (deleted rel paths, errors)."""
    deleted, errors = [], []
    want = {str(e).lower() for e in exts}
    for p in _image_files(Path(root), want):
        if is_ai_generated_filename(p):
            continue
        try:
            p.unlink()
            deleted.append(p.relative_to(root).as_posix())
        except Exception as e:
            errors.append(f"{p.name}: {e}")
    return deleted, errors
