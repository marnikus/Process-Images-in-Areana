"""The Firefox job's journal — what survives a crash, and nothing else.

Chrome keeps the whole job in memory because every step is one CDP call away;
the Firefox job crosses a macro boundary per phase, so "what was already proved"
has to live somewhere a *new* process can read it. One JSON file per image
(`<config>/firefox_jobs/<image-id>.json`, `persistence.json_store` — the single
atomic writer), written at every checkpoint the recovery decision table needs:

    phase        baseline | prepared | submitted | correlated | downloaded | saved
    token        the job's `[JOB-ID: …]` correlation id
    image_path   the source image (so a stale journal can never be replayed)
    tab_id       the pool entry the job ran on
    final_path   where the file will land (unique `_AI` name, planned up front)
    src          the correlated result URL, once the page answered it
    submit_clicks how many Send clicks the macro recorded (0/1)
    attempts     how many dispatches this image has had

Imports: persistence + stdlib only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.persistence.json_store import load_json, save_json_atomic

DIR_NAME = "firefox_jobs"
PHASES = ("baseline", "prepared", "submitted", "correlated", "downloaded", "saved")
TERMINAL = ("saved",)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_dir(bridge) -> Path:
    return Path(getattr(bridge.config, "dir", "config")).expanduser()


def path_for(bridge, img) -> Path:
    """One journal per image (id sanitized: it becomes a file name)."""
    safe = "".join(ch for ch in str(getattr(img, "id", "") or "image") if ch.isalnum() or ch in "-_")
    return _config_dir(bridge) / DIR_NAME / f"{safe or 'image'}.json"


def read(bridge, img) -> dict:
    """The journal for this image, or {} (a missing/corrupt file is simply not evidence)."""
    data = load_json(path_for(bridge, img), {})
    return data if isinstance(data, dict) else {}


def write(bridge, img, **fields) -> dict:
    """Merge fields into the journal and persist atomically; returns the merged dict."""
    data = read(bridge, img)
    data.update({k: v for k, v in fields.items() if v is not None})
    data["updated_at"] = now_iso()
    data.setdefault("image_id", str(getattr(img, "id", "")))
    data.setdefault("image_path", str(getattr(img, "absolute_path", "")))
    try:
        save_json_atomic(path_for(bridge, img), data)
    except OSError:
        pass                      # a journal that cannot be written is never fatal
    return data


def clear(bridge, img) -> None:
    """Forget the job — the last act of a successful save."""
    try:
        path_for(bridge, img).unlink(missing_ok=True)
    except OSError:
        pass


def belongs_to(data: dict, img) -> bool:
    """True when this journal is about this very image (never replay a foreign one)."""
    if not data:
        return False
    mine = str(getattr(img, "absolute_path", "") or "")
    theirs = str(data.get("image_path", "") or "")
    return bool(mine) and mine == theirs


def phase_reached(data: dict, phase: str) -> bool:
    """True when the journal's phase is at least `phase` in the recorded order."""
    try:
        return PHASES.index(str(data.get("phase", ""))) >= PHASES.index(phase)
    except ValueError:
        return False


def attempts(data: dict) -> int:
    """How many dispatches this image has had (for the log, never for a decision)."""
    try:
        return max(0, int(data.get("attempts", 0) or 0))
    except Exception:
        return 0
