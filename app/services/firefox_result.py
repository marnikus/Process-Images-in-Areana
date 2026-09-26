"""The Firefox job's result bytes → a validated, atomically saved `_AI` file.

Chrome's tail (download → validate → save) is three blocks that write straight
into the queue's image; the Firefox lane needs the same rules **plus** a
recoverable intermediate state, because the bytes travel through a macro there:
a crash between "the page produced them" and "the file is on disk" must be
finishable without generating the image again.

Owns:
* `fetch_bytes` — the shared plain-HTTP download (the extracted Chrome fallback)
  for an `https:` src, with the same HTML/size rejection;
* `validate_bytes` — PIL, width/height > 0, > 100 bytes (Chrome's rule);
* the staging file `<dir>/.<final-name>.part` and `finalize` onto the final name
  (`naming.atomic_write_bytes`, RULE 23) — never overwriting an existing `_AI`
  file (`naming.get_output_path` is the one naming authority).

Imports: browser + core layers, stdlib.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from app.browser.image_fetch import MIN_BYTES, fetch_bytes
from app.core.naming import OutputSpec, atomic_write_bytes, get_output_path

log = logging.getLogger("arena")

STAGING_SUFFIX = ".part"


def output_spec(settings) -> OutputSpec:
    """The user's output settings as one validated spec (Chrome's own fields)."""
    out = getattr(settings, "output", {}) or {}
    return OutputSpec(
        suffix=out.get("suffix", "_AI"),
        preserve_format=out.get("preserve_format", True),
        overwrite=out.get("overwrite", False),
        unique_template=out.get("unique_suffix_template", "{base}_AI_{n}{ext}"),
    )


def plan_output(img, settings, ext: str | None = None) -> Path:
    """Where this job's file will land (unique `_AI` name beside the source).

    `ext` is the validated downloaded format when it is already known; without it
    the source's own extension is the plan (and the save re-resolves anyway, so an
    `_AI` file that appeared meanwhile is never overwritten — RULE 23).
    """
    spec = output_spec(settings)
    spec.downloaded_ext = ext or None
    return Path(get_output_path(Path(img.absolute_path), spec))


def find_recent_output(source_path: Path, settings, since_iso: str) -> Path | None:
    """Newest `<base>_AI*` sibling written while this job was running (recovery evidence).

    The planned name alone cannot cover a format the download chose (a PNG upload can
    come back as JPEG), so the *family* plus the journal's own start time is the
    window. The caller validates the bytes before anything is called completed.
    """
    source = Path(source_path)
    spec = output_spec(settings)
    since = timestamp_of(since_iso)
    best: Path | None = None
    for candidate in source.parent.glob(f"{source.stem}{spec.suffix}*"):
        if not candidate.is_file() or (since > 0 and _mtime(candidate) < since):
            continue
        if best is None or _mtime(candidate) > _mtime(best):
            best = candidate
    return best


def _mtime(path: Path) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return -1.0


def timestamp_of(text: str) -> float:
    """A journal's ISO stamp as a POSIX number, or -1 when it cannot be read."""
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(text)).timestamp()
    except Exception:
        return -1.0


def find_recent_output(source_path: Path, settings, since_iso: str):
    """The newest `_AI` sibling written since `since_iso` — this job's own output.

    The planned name cannot cover a format the download decided (a PNG upload may
    come back as JPEG), so the family match plus the journal's own start time is
    the honest window; the bytes are validated by the caller before anything is
    marked completed.
    """
    source = Path(source_path)
    spec = output_spec(settings)
    since = timestamp_of(since_iso)
    best = None
    for candidate in source.parent.glob(f"{source.stem}{spec.suffix}*"):
        if not candidate.is_file() or (since > 0 and _mtime(candidate) < since):
            continue
        if best is None or _mtime(candidate) > _mtime(best):
            best = candidate
    return best


def final_file_evidence(final_path: Path) -> bool:
    """True when a non-empty file already sits at the planned final name."""
    try:
        return Path(final_path).is_file() and Path(final_path).stat().st_size > 0
    except OSError:
        return False


def staging_path(final_path: Path) -> Path:
    """`<dir>/.<name>.part` — a dot-file with a non-image suffix, invisible to scans."""
    final_path = Path(final_path)
    return final_path.parent / f".{final_path.name}{STAGING_SUFFIX}"


def validate_bytes(data: bytes) -> tuple:
    """(ok, ext, note) — Chrome's rule: PIL-decodable, sized, over 100 bytes, not HTML."""
    raw = bytes(data or b"")
    low = raw[:200].lower()
    if b"<html" in low or b"<!doctype" in low:
        return False, "", "the bytes are an HTML page, not an image"
    if len(raw) < MIN_BYTES:
        return False, "", f"too small ({len(raw)} bytes)"
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(raw))
        if not (image.width and image.height):
            return False, "", "the image has no pixels"
        fmt = (image.format or "PNG").lower()
        return True, (".jpg" if fmt == "jpeg" else f".{fmt}"), f"{fmt} {image.width}x{image.height}"
    except Exception as exc:
        return False, "", f"unreadable image ({exc})"


def store_staging(final_path: Path, data: bytes) -> tuple:
    """(ok, note) — write the bytes to the staging file (atomic, never a partial)."""
    try:
        atomic_write_bytes(Path(final_path).parent, staging_path(final_path), data)
        return True, f"staged {len(data)} bytes at {staging_path(final_path).name}"
    except OSError as exc:
        return False, f"staging save failed: {exc}"
    except Exception as exc:
        return False, f"staging save failed: {exc}"


def staged_bytes(final_path: Path) -> bytes:
    """The staging file's bytes, or b"" when there is none (a torn file reads as empty)."""
    try:
        return Path(staging_path(final_path)).read_bytes()
    except OSError:
        return b""


def discard_staging(final_path: Path) -> None:
    """Drop the staging file after a successful final save (best effort)."""
    try:
        Path(staging_path(final_path)).unlink(missing_ok=True)
    except OSError:
        pass


def finalize(final_path: Path, data: bytes) -> tuple:
    """(ok, note) — the atomic final save (mkstemp + replace), then drop the staging."""
    try:
        atomic_write_bytes(Path(final_path).parent, Path(final_path), bytes(data))
    except OSError as exc:
        return False, f"save failed: {exc}"
    except Exception as exc:
        return False, f"save failed: {exc}"
    discard_staging(final_path)
    return True, f"saved {len(data)} bytes"


def download(src: str, timeout: int = 45) -> tuple:
    """(ok, data, note) — the shared HTTPS fetch (no page, no CDP), honest failures."""
    ok, data, _ctype, err = fetch_bytes(str(src or ""), timeout=timeout)
    if not ok:
        return False, b"", err or "download failed"
    return True, data, f"downloaded {len(data)} bytes"
