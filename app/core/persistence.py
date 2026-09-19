import json
from pathlib import Path

from .models import AppState
from ..persistence.json_store import atomic_write_json

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
    """Atomic write: temp file in same dir + replace (json_store)."""
    atomic_write_json(Path(path), state.to_dict())

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
    atomic_write_json(preset_path, data)

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
    from .enums import ImageStatus, JobStatus

    if root_path is None:
        root_str = state.folder.get("root_path", "")
        if not root_str:
            return {"error": "No root path configured"}
        root_path = Path(root_str)

    root_path = Path(root_path)
    if not root_path.exists():
        return {"error": f"Root path does not exist: {root_path}"}

    # Scan current
    supported = state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"])
    ignore_ai = state.folder.get("ignore_ai_suffix", True)
    current_scan = scan_folder(root_path, set(supported), ignore_ai)

    # Previous as scan dicts
    prev_scan = [
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

    changes = detect_changes(prev_scan, current_scan)

    # Handle removed: mark as skipped with error
    removed_rels = {r["relative_path"] for r in changes["removed"]}
    for img in state.images:
        if img.relative_path in removed_rels:
            if img.status not in [ImageStatus.SKIPPED.value, ImageStatus.COMPLETED.value]:
                img.status = ImageStatus.SKIPPED.value
                img.error = "Source file removed"
                img.selected = False

    # Handle changed: if previously completed, reset to pending
    for ch in changes["changed"]:
        old = ch["old"]
        new = ch["new"]
        # Find image
        for img in state.images:
            if img.relative_path == old["relative_path"]:
                # Update metadata
                img.size = new["size"]
                img.mtime = new["mtime"]
                img.fingerprint = new["fingerprint"]
                img.absolute_path = new["absolute_path"]
                # If completed, reset
                if img.status == ImageStatus.COMPLETED.value:
                    img.status = ImageStatus.PENDING.value
                    img.selected = True
                    img.output_path = None
                    img.error = "Source changed, needs reprocessing"
                break

    # Handle added: add as pending
    for added in changes["added"]:
        from .models import ImageItem
        new_img = ImageItem.from_scan_dict(added, selected=False)
        # Avoid duplicate
        if not any(i.relative_path == new_img.relative_path for i in state.images):
            state.images.append(new_img)

    # Handle interrupted jobs
    interrupted_count = 0
    for job in state.jobs:
        if job.status in [JobStatus.PROCESSING.value, JobStatus.SUBMITTED.value, JobStatus.WAITING_GENERATION.value, JobStatus.ATTACHING.value]:
            job.status = JobStatus.INTERRUPTED.value
            job.error = "Interrupted by crash/restart, requires confirmation"
            interrupted_count += 1
            # Also mark image as failed or pending?
            for img in state.images:
                if img.id == job.image_id and img.status == ImageStatus.PROCESSING.value:
                    img.status = ImageStatus.FAILED.value
                    img.error = "Interrupted"

    state.recalculate_progress()
    return {
        "added": len(changes["added"]),
        "removed": len(changes["removed"]),
        "changed": len(changes["changed"]),
        "interrupted": interrupted_count,
    }
