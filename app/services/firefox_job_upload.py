"""Firefox job upload staging — source checks + the uniquely named copy (design D-3/D-4).

Firefox cannot fill `input[type=file]` from an extension, so the phase macro
types a path into the OS file dialog. Two rules make that safe:

* the source is checked BEFORE any page action — exists, supported extension,
  PIL-readable, content matching the extension (a missing / unsupported file
  fails with zero macro launches);
* the dialog receives a COPY named `arena_<corr><ext>` in an ASCII-only folder
  — XType never has to type Unicode, and the attachment preview is verified by
  that exact unique name, which also exposes a stale attachment of another job.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

SUPPORTED = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
UPLOADS_DIR = "uploads"


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


def staged_name(corr: str, source) -> str:
    """`arena_<corr><ext>` — the name the preview must carry."""
    return f"arena_{corr}{Path(source).suffix.lower()}"


def _is_ascii(path: Path) -> bool:
    return str(path).isascii()


def upload_dir(config_dir) -> Path:
    """The first ASCII-only staging folder: config → temp → public (else config)."""
    base = Path(config_dir) / "uivision" / UPLOADS_DIR
    candidates = [base, Path(tempfile.gettempdir()) / "arena_uploads"]
    public = os.environ.get("PUBLIC", "")
    if public:
        candidates.append(Path(public) / "arena_uploads")
    return next((c for c in candidates if _is_ascii(c)), base)


def stage_upload(config_dir, source, corr: str) -> Path:
    """Copy the source to the staging folder under its unique name; the copy's path."""
    folder = upload_dir(config_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / staged_name(corr, source)
    shutil.copy2(source, target)
    return target


def drop_staged(path) -> None:
    """Remove a staged copy (best effort — a leftover is harmless, never fatal)."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
