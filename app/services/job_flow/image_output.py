"""Save a generated image beside its source — one owner for both lanes.

* `output_spec(settings, ext)` — the `_AI` naming settings (`settings.output`);
* `save_beside(source, data, spec)` — `naming.get_output_path` (never
  overwriting unless configured) + `naming.atomic_write_bytes` in the source
  folder, retrying a transient sharing violation (Windows 32/33, an antivirus
  or thumbnailer holding the new file) — a failure is an `OutputError` with the
  OS reason, never swallowed.

Moved out of `firefox_job_output` on 2026-09-26 so the Chrome lane saves the
same way (docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md).
Imports: core + utils only.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.core.naming import OutputSpec, atomic_write_bytes, get_output_path
from app.utils.http_image import OutputError

SAVE_TRIES = 3


def output_spec(settings, ext: str) -> OutputSpec:
    """The naming settings of `settings.output` for bytes of extension `ext`."""
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
