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

`fetch`'s gate lives in `utils/http_image` and `save_beside` / `output_spec` in
`services/job_flow/image_output` since 2026-09-26 — the Chrome lane uses the same ones
(docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md); the
names stay importable from here.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Optional

from app.core.naming import parse_ai_output
from app.services.job_flow.image_output import SAVE_TRIES, output_spec, save_beside  # noqa: F401 — re-export (one owner)
from app.utils.http_image import MIN_BYTES, OutputError, check_response, fetch_image  # noqa: F401 — re-export


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(src: str, timeout: float, opener=None) -> bytes:
    """GET the result; the checked bytes or OutputError (`utils.http_image` owns the gate)."""
    return fetch_image(src, timeout, opener)[0]


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
