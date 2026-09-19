import json
import os
import tempfile
from pathlib import Path
from typing import Optional
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

def save_state(state: AppState, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = state.to_dict()
    # Atomic write: write to temp file in same dir, then replace
    fd, tmp_path_str = tempfile.mkstemp(prefix=path.stem + "_", suffix=".json.tmp", dir=str(path.parent))
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

def save_preset(state: AppState, preset_path: Path) -> None:
    """Save preset JSON containing UI params (urls, prompt, settings, folder) without jobs/images."""
    preset_path = Path(preset_path)
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": state.version,
        "urls": [u.__dict__ for u in state.urls],
        "folder": state.folder,
        "prompt": state.prompt,
        "settings": state.settings.__dict__,
    }
    fd, tmp_path_str = tempfile.mkstemp(prefix=preset_path.stem + "_", suffix=".json.tmp", dir=str(preset_path.parent))
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(preset_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

def load_preset(preset_path: Path) -> dict:
    preset_path = Path(preset_path)
    if not preset_path.exists():
        raise FileNotFoundError(f"Preset not found: {preset_path}")
    with preset_path.open("r", encoding="utf-8") as f:
        return json.load(f)

def reconcile_with_filesystem(state: AppState, root_path: Path | None = None) -> dict:
    """
    Reconcile saved state with current filesystem.
    Returns dict of changes.
    - Marks missing source files as skipped
    - Detects changed files (size/mtime) and resets completed to pending if needed
    - Does not auto-resubmit interrupted jobs
    """
    from .scanner import scan_folder, detect_changes

    root_path, err = _reconcile_root(state, root_path)
    if err:
        return {"error": err}
    changes = detect_changes(_prev_scan_dicts(state.images),
                             scan_folder(root_path, *_reconcile_filters(state)))
    _reconcile_removed(state, changes["removed"])
    _reconcile_changed(state, changes["changed"])
    _reconcile_added(state, changes["added"])
    interrupted = _reconcile_interrupted(state)
    state.recalculate_progress()
    return {"added": len(changes["added"]), "removed": len(changes["removed"]),
            "changed": len(changes["changed"]), "interrupted": interrupted}


def _reconcile_root(state: AppState, root_path: Path | None):
    """(resolved root Path, None) or (None, error dict) for the scan root."""
    if root_path is None:
        root_str = state.folder.get("root_path", "")
        if not root_str:
            return None, {"error": "No root path configured"}
        root_path = Path(root_str)
    root_path = Path(root_path)
    if not root_path.exists():
        return None, {"error": f"Root path does not exist: {root_path}"}
    return root_path, None


def _reconcile_filters(state: AppState) -> tuple:
    """(supported extensions set, ignore_ai_suffix) from state folder config."""
    supported = state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"])
    ignore_ai = state.folder.get("ignore_ai_suffix", True)
    return set(supported), ignore_ai


def _prev_scan_dicts(images: list) -> list:
    """Saved images as scan dicts for detect_changes comparison."""
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
        for img in images
    ]


def _reconcile_removed(state: AppState, removed: list) -> None:
    """Mark images whose source file vanished as skipped (not completed ones)."""
    from .enums import ImageStatus
    removed_rels = {r["relative_path"] for r in removed}
    for img in state.images:
        if img.relative_path in removed_rels:
            if img.status not in [ImageStatus.SKIPPED.value, ImageStatus.COMPLETED.value]:
                img.status = ImageStatus.SKIPPED.value
                img.error = "Source file removed"
                img.selected = False


def _reconcile_changed(state: AppState, changed: list) -> None:
    """Update metadata for changed files; reset completed ones to pending."""
    from .enums import ImageStatus
    for ch in changed:
        old, new = ch["old"], ch["new"]
        for img in state.images:
            if img.relative_path == old["relative_path"]:
                _apply_changed_metadata(img, new, ImageStatus)
                break


def _apply_changed_metadata(img, new: dict, ImageStatus) -> None:
    """One changed image: refresh metadata, reset completed to pending."""
    img.size = new["size"]
    img.mtime = new["mtime"]
    img.fingerprint = new["fingerprint"]
    img.absolute_path = new["absolute_path"]
    if img.status == ImageStatus.COMPLETED.value:
        img.status = ImageStatus.PENDING.value
        img.selected = True
        img.output_path = None
        img.error = "Source changed, needs reprocessing"


def _reconcile_added(state: AppState, added: list) -> None:
    """Append genuinely new scan entries as unselected pending images."""
    from .models import ImageItem
    for entry in added:
        new_img = ImageItem.from_scan_dict(entry, selected=False)
        if not any(i.relative_path == new_img.relative_path for i in state.images):  # avoid duplicate
            state.images.append(new_img)


def _reconcile_interrupted(state: AppState) -> int:
    """Mark in-flight jobs as interrupted; their processing images as failed."""
    from .enums import ImageStatus, JobStatus
    interrupted_count = 0
    for job in state.jobs:
        if job.status in [JobStatus.PROCESSING.value, JobStatus.SUBMITTED.value,
                          JobStatus.WAITING_GENERATION.value, JobStatus.ATTACHING.value]:
            job.status = JobStatus.INTERRUPTED.value
            job.error = "Interrupted by crash/restart, requires confirmation"
            interrupted_count += 1
            _fail_interrupted_image(state, job, ImageStatus)
    return interrupted_count


def _fail_interrupted_image(state: AppState, job, ImageStatus) -> None:
    """Image of an interrupted job (when still processing) -> failed."""
    for img in state.images:
        if img.id == job.image_id and img.status == ImageStatus.PROCESSING.value:
            img.status = ImageStatus.FAILED.value
            img.error = "Interrupted"
