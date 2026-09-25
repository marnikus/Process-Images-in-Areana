"""Firefox job output — fetch, validate, stage and save beside the source (design §6.5).

The correlated result `src` is a presigned https URL that downloads without
cookies (Chrome's own Python fallback relies on the same fact), so the Firefox
job fetches it from Python and never needs the browser's download folder:

* `fetch` rejects HTTP ≠ 200, an HTML page, a body under 100 bytes (Chrome's
  rule) and a body shorter than its Content-Length (partial);
* `validate_image` = PIL verify + full decode; the format decides the extension
  (Chrome's `f".{format}"` rule, so names match the Chrome lane);
* `stage_bytes` secures the bytes in the job folder first (temp + fsync +
  rename) — a failed save keeps them, so a retry re-saves without generating;
* `save_beside` = the Chrome naming (`OutputSpec` from settings, `_AI`, never
  overwriting) + `naming.atomic_write_bytes` in the source folder, retrying a
  transient sharing violation; `find_saved` reconciles a save whose state write
  was interrupted (a sibling of the `_AI` family with the same SHA-256).
"""

from __future__ import annotations

import hashlib
import io
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional

from app.core.naming import OutputSpec, atomic_write_bytes, get_output_path, parse_ai_output

MIN_BYTES = 100
SAVE_TRIES = 3
_UA = {"User-Agent": "Mozilla/5.0 (Arena Image Processor)"}


class OutputError(Exception):
    """A result that must not be saved (named reason)."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_response(status: int, ctype: str, length, data: bytes) -> None:
    """The download gate (raises OutputError with the reason)."""
    if status != 200:
        raise OutputError(f"HTTP {status}")
    head = data[:64].lstrip().lower()
    if "text/html" in (ctype or "").lower() or head.startswith((b"<!doctype", b"<html")):
        raise OutputError("got an HTML page, not an image")
    if len(data) < MIN_BYTES:
        raise OutputError(f"only {len(data)} bytes")
    if length not in (None, "") and str(length).isdigit() and int(length) != len(data):
        raise OutputError(f"partial download {len(data)}/{length} bytes")


def fetch(src: str, timeout: float, opener=None) -> bytes:
    """GET the result; the checked bytes or OutputError."""
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(urllib.request.Request(src, headers=_UA), timeout=timeout) as resp:
            data = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
            headers = getattr(resp, "headers", {}) or {}
            check_response(status, headers.get("Content-Type", ""), headers.get("Content-Length"), data)
            return data
    except OutputError:
        raise
    except Exception as exc:
        raise OutputError(f"download failed: {exc}") from exc


def validate_image(data: bytes) -> str:
    """The saved extension (`.png`, `.jpeg`, `.webp`) of decodable image bytes."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            fmt, size = str(im.format or "").lower(), (im.width, im.height)
    except Exception as exc:
        raise OutputError(f"corrupt image: {exc}") from exc
    if fmt not in ("png", "jpeg", "webp") or not all(size):
        raise OutputError(f"unexpected image format {fmt or '?'}")
    return f".{fmt}"


def stage_bytes(job_dir, data: bytes) -> Path:
    """`<job_dir>/download.bin` via temp + fsync + rename; its path."""
    folder = Path(job_dir)
    folder.mkdir(parents=True, exist_ok=True)
    part, final = folder / "download.part", folder / "download.bin"
    with open(part, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    part.replace(final)
    return final


def read_staged(path, expected_sha: str) -> Optional[bytes]:
    """The staged bytes when present AND matching the journalled hash."""
    try:
        data = Path(path).read_bytes()
    except (OSError, TypeError):
        return None
    return data if sha256(data) == expected_sha else None


def output_spec(settings, ext: str) -> OutputSpec:
    """The Chrome lane's naming settings (`single_job_runner.save_image`)."""
    out = getattr(settings, "output", None) or {}
    return OutputSpec(suffix=out.get("suffix", "_AI"), preserve_format=out.get("preserve_format", True),
                      overwrite=out.get("overwrite", False), downloaded_ext=ext,
                      unique_template=out.get("unique_suffix_template", "{base}_AI_{n}{ext}"))


def _transient(exc: OSError) -> bool:
    """Sharing-violation class (Windows 32/33, or a PermissionError on replace)."""
    return getattr(exc, "winerror", None) in (32, 33) or isinstance(exc, PermissionError)


def save_beside(source, data: bytes, spec: OutputSpec, sleep=time.sleep) -> Path:
    """Atomic save next to the source under the `_AI` rule; transient errors retried."""
    source = Path(source)
    for attempt in range(1, SAVE_TRIES + 1):
        target = get_output_path(source, spec)
        try:
            return atomic_write_bytes(source.parent, target, data)
        except OSError as exc:
            if attempt == SAVE_TRIES or not _transient(exc):
                raise OutputError(f"save failed: {exc}") from exc
            sleep(0.5 * attempt)
    raise OutputError("save failed")  # pragma: no cover — loop always returns or raises


def find_saved(source, expected_sha: str, suffix: str = "_AI") -> Optional[Path]:
    """An `_AI`-family sibling of `source` whose bytes hash to `expected_sha`."""
    source = Path(source)
    prefix = f"{source.stem}{suffix}"
    try:
        siblings = sorted(p for p in source.parent.iterdir() if p.name.startswith(prefix))
    except OSError:
        return None
    for candidate in siblings:
        parsed = parse_ai_output(candidate.stem, suffix)
        if parsed and parsed[0] == source.stem and read_staged(candidate, expected_sha):
            return candidate
    return None
