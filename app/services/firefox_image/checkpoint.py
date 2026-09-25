"""Per-image Firefox job checkpoint (I-65).

The file is the book. Restoring it replaces the live dict — it does not merge
with a later partial edit (the same rule as restoring a saved settings
checkpoint over a newer draft). Submit intent is written before Send fires.

Imports: persistence json_store + stdlib.
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import load_json, save_json_atomic

_EMPTY = {"jobs": {}}


def store_path(bridge) -> Path:
    """`config/firefox_jobs.json` beside the other stores."""
    base = getattr(getattr(bridge, "config", None), "dir", None) or "config"
    return Path(base) / "firefox_jobs.json"


def load_book(bridge, image_id: str) -> dict:
    """This image's checkpoint, or {} when none was saved."""
    data = load_json(store_path(bridge), _EMPTY)
    row = (data.get("jobs") or {}).get(image_id or "") or {}
    return dict(row) if isinstance(row, dict) else {}


def save_book(bridge, image_id: str, book: dict) -> None:
    """Rewrite this image's record. Other images are left as they were."""
    path = store_path(bridge)
    data = load_json(path, _EMPTY)
    jobs = dict(data.get("jobs") or {})
    jobs[image_id] = dict(book)
    save_json_atomic(path, {"jobs": jobs})


def stamp_path(source: str) -> Path:
    """Sidecar written before the atomic save, cleared after the queue write."""
    file = Path(source or "image")
    return file.with_name(f".{file.name}.arena-saving")


def mark_saving(source: str) -> None:
    """Note that this attempt is about to create the output file."""
    path = stamp_path(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("saving\n", encoding="utf-8")


def clear_saving(source: str) -> None:
    """The queue write landed — the stamp must not reconcile a later regenerate."""
    try:
        stamp_path(source).unlink(missing_ok=True)
    except OSError:
        pass


def saving_marked(source: str) -> bool:
    """True while an interrupted save still owns the sibling output."""
    try:
        return stamp_path(source).is_file()
    except OSError:
        return False
