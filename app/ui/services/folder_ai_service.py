"""Folder-AI Service — disk _AI worker extracted from bridge.py (R3).

Runs off the UI thread; takes the bridge opaque (state/log/save/scan-flag),
like `push_urls_undo`. Wraps `app.core.folder_ai` (pure disk ops) and syncs
the image queue to the renames/deletes. No Qt.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List

from app.core.folder_ai import delete_non_ai_images, strip_ai_suffixes
from app.utils.hashing import fingerprint_from_path_stat


def drop_missing_queue_images(images: List, root_path: Path, deleted) -> None:
    """Forget queue entries whose files were deleted."""
    try:
        gone = {str(Path(root_path, r).resolve()) for r in deleted}
        images[:] = [i for i in images if i.absolute_path not in gone]
    except Exception:
        pass


def rename_queue_images(images: List, root_path: Path, pairs) -> None:
    """Point queue entries at renamed files (stats preserved)."""
    try:
        by_old = {str(Path(root_path, old).resolve()): new for old, new in pairs}
        for img in images:
            new_rel = by_old.get(img.absolute_path)
            if not new_rel:
                continue
            img.relative_path = new_rel
            img.absolute_path = str(Path(root_path, new_rel).resolve())
            img.filename = Path(new_rel).name
            img.base_name = Path(new_rel).stem
            img.fingerprint = fingerprint_from_path_stat(new_rel, img.size, img.mtime)
    except Exception:
        pass


def folder_ai_worker(bridge, root_path: Path, exts: set, mode: str) -> None:
    """Rename/delete _AI files on disk, sync queue. Off UI thread."""
    try:
        if mode == "only":
            deleted, errors = delete_non_ai_images(root_path, exts)
            drop_missing_queue_images(bridge.state.images, root_path, deleted)
            bridge._log(f"Only _AI: deleted {len(deleted)} files from {root_path}", "warn")
        else:
            pairs, skipped, errors = strip_ai_suffixes(root_path, exts)
            rename_queue_images(bridge.state.images, root_path, pairs)
            bridge._log(f"Drop _AI: renamed {len(pairs)}, skipped {skipped} in {root_path}", "warn")
        for err in errors[:3]:
            bridge._log(str(err), "warn")
        bridge.state.recalculate_progress()
        bridge._save_arena()
    except Exception as e:
        bridge._log(f"Folder _AI op failed: {e}", "error")
    finally:
        bridge._scan_in_progress = False


def submit_folder_ai(bridge, root_path: Path, exts: set, mode: str) -> None:
    """Run the folder _AI worker off the UI thread."""
    if bridge._thumb_executor:
        bridge._thumb_executor.submit(folder_ai_worker, bridge, root_path, exts, mode)
    else:
        threading.Thread(
            target=folder_ai_worker, args=(bridge, root_path, exts, mode), daemon=True
        ).start()
