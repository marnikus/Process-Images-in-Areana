"""Firefox job upload — source checks + the path the OS file dialog receives (design D-3/D-4).

Firefox cannot fill `input[type=file]` from an extension, so the attach macro
pastes a path into the OS file dialog (`uivision/file_dialog`). Rules:

* the source is checked BEFORE any page action — exists, supported extension,
  PIL-readable, content matching the extension (a missing / unsupported file
  fails with zero macro launches);
* the dialog receives the QUEUE FILE ITSELF by its absolute path (live fix
  2026-09-26: the old `arena_<corr><ext>` staging copy was handed over as a
  relative `config/uivision/uploads/…` path the dialog rejected). The copy
  existed so XType never typed Unicode — the path is pasted now — and so the
  preview had a unique name; the preview must now carry the queue file's name,
  and the baseline still refuses a composer holding any earlier attachment;
* `drop_staged` only ever deletes a legacy `arena_*` copy inside an uploads
  folder — a journal's `staged_upload` now names the owner's image.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

SUPPORTED = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
_LEGACY_DIRS = {"uploads", "arena_uploads"}   # where the pre-2026-09-26 copies lived


def _pil_format(path: Path) -> Optional[str]:
    """PIL's format name for a readable image, else None."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
            return str(im.format or "").upper() or None
    except Exception:
        return None


def check_source(path) -> str:
    """'' when the source may be uploaded, else the honest reason (RULE 4)."""
    source = Path(path)
    if not source.is_file():
        return f"source image missing: {source.name}"
    wanted = SUPPORTED.get(source.suffix.lower())
    if wanted is None:
        return f"unsupported file type {source.suffix or '(none)'} — PNG, JPEG or WebP only"
    actual = _pil_format(source)
    if actual is None:
        return f"source is not a readable image: {source.name}"
    if actual != wanted:
        return f"source content is {actual} but the extension says {wanted}: {source.name}"
    return ""


def upload_path(source) -> str:
    """The queue file's absolute path — what the dialog opens (never resolved to UNC)."""
    return os.path.abspath(str(source))


def _is_legacy_copy(path: Path) -> bool:
    return path.name.startswith("arena_") and path.parent.name in _LEGACY_DIRS


def drop_staged(path) -> None:
    """Remove a legacy staging copy (best effort); anything else — the owner's image — stays."""
    if not path or not _is_legacy_copy(Path(path)):
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
