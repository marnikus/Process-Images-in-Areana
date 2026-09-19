"""Persistence — C5 refactor with predicate tables and small helpers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import AppState


def load_state(path: Path) -> AppState:
    path = Path(path)
    if not path.exists():
        return AppState()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return AppState.from_dict(data)
    except Exception as e:
        print(f"Failed to load state from {path}: {e}, returning empty state")
        return AppState()


def _atomic_json_write(target: Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=target.stem + "_", suffix=".json.tmp", dir=str(target.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(target)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def save_state(state: AppState, path: Path) -> None:
    path = Path(path)
    _atomic_json_write(path, state.to_dict())


def save_preset(state: AppState, preset_path: Path) -> None:
    preset_path = Path(preset_path)
    data = {
        "version": state.version,
        "urls": [u.__dict__ for u in state.urls],
        "folder": state.folder,
        "prompt": state.prompt,
        "settings": state.settings.__dict__,
    }
    _atomic_json_write(preset_path, data)


def load_preset(preset_path: Path) -> dict:
    preset_path = Path(preset_path)
    if not preset_path.exists():
        raise FileNotFoundError(f"Preset not found: {preset_path}")
    with preset_path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---- reconcile helpers (C5 predicate table + small funcs) ----

def _resolve_root(state: AppState, root_path: Path | None) -> tuple[Path | None, dict | None]:
    if root_path is None:
        root_str = state.folder.get("root_path", "")
        if not root_str:
            return None, {"error": "No root path configured"}
        root_path = Path(root_str)
    root_path = Path(root_path)
    if not root_path.exists():
        return None, {"error": f"Root path does not exist: {root_path}"}
    return root_path, None


def _build_prev_scan(state: AppState) -> list[dict]:
    return [
        {
            "relative_path": img.relative_path,
            "absolute_path": img.absolute_path,
            "filename": img.filename,
            "base_name": img.base_name,
            "extension": img.extension,
            "size": img.size,
            "mtime": img.mtime,
            "fingerprint": img.fingerprint,
            "id": img.id,
        }
        for img in state.images
    ]


def _handle_removed(state: AppState, removed: list[dict]) -> None:
    from .enums import ImageStatus
    removed_rels = {r["relative_path"] for r in removed}
    for img in state.images:
        if img.relative_path in removed_rels:
            if img.status not in [ImageStatus.SKIPPED.value, ImageStatus.COMPLETED.value]:
                img.status = ImageStatus.SKIPPED.value
                img.error = "Source file removed"
                img.selected = False


def _handle_changed(state: AppState, changed: list[dict]) -> None:
    from .enums import ImageStatus
    for ch in changed:
        old = ch["old"]
        new = ch["new"]
        for img in state.images:
            if img.relative_path == old["relative_path"]:
                img.size = new["size"]
                img.mtime = new["mtime"]
                img.fingerprint = new["fingerprint"]
                img.absolute_path = new["absolute_path"]
                if img.status == ImageStatus.COMPLETED.value:
                    img.status = ImageStatus.PENDING.value
                    img.selected = True
                    img.output_path = None
                    img.error = "Source changed, needs reprocessing"
                break


def _handle_added(state: AppState, added: list[dict]) -> None:
    from .models import ImageItem
    for item in added:
        new_img = ImageItem.from_scan_dict(item, selected=False)
        if not any(i.relative_path == new_img.relative_path for i in state.images):
            state.images.append(new_img)


def _handle_interrupted(state: AppState) -> int:
    from .enums import ImageStatus, JobStatus
    # predicate table of in-progress statuses (C5)
    interrupted_statuses = {
        JobStatus.ATTACHING.value,
        JobStatus.SUBMITTED.value,
        JobStatus.WAITING_GENERATION.value,
        JobStatus.DOWNLOADING.value,
        JobStatus.VALIDATING.value,
        JobStatus.SAVING.value,
        JobStatus.PROMPT_INSERTED.value,
        JobStatus.BASELINE_CAPTURED.value,
    }
    count = 0
    for job in state.jobs:
        if job.status in interrupted_statuses:
            job.status = JobStatus.INTERRUPTED.value
            job.error = "Interrupted by crash/restart, requires confirmation"
            count += 1
            for img in state.images:
                if img.id == job.image_id and img.status == ImageStatus.PROCESSING.value:
                    img.status = ImageStatus.FAILED.value
                    img.error = "Interrupted"
    return count


def _reconcile_diff(state: AppState, root: Path) -> dict:
    """Diff persisted queue vs a fresh scan (spec object in, changes dict out)."""
    from .scanner import ScanSpec, scan_folder, detect_changes  # local: circular import guard

    supported = state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"])
    ignore_ai = state.folder.get("ignore_ai_suffix", True)
    spec = ScanSpec(supported_exts=set(supported), ignore_ai_suffix=ignore_ai)
    current_scan = scan_folder(root, spec)
    prev_scan = _build_prev_scan(state)
    return detect_changes(prev_scan, current_scan)


def reconcile_with_filesystem(state: AppState, root_path: Path | None = None) -> dict:
    root, err = _resolve_root(state, root_path)
    if err:
        return err
    assert root is not None

    changes = _reconcile_diff(state, root)

    # predicate table for handlers
    handlers = {
        "removed": _handle_removed,
        "changed": _handle_changed,
        "added": _handle_added,
    }
    for key, handler in handlers.items():
        handler(state, changes[key])

    interrupted = _handle_interrupted(state)
    state.recalculate_progress()
    return {
        "added": len(changes["added"]),
        "removed": len(changes["removed"]),
        "changed": len(changes["changed"]),
        "interrupted": interrupted,
    }
