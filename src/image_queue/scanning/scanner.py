"""Explicit scan/reconcile only. A failed traversal never marks an unseen file missing."""

import hashlib
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from image_queue.domain.validation import ContractError
from image_queue.scanning.files import source_paths
from image_queue.scanning.images import image_metadata, read_source


class FolderScanner:
    def scan(self, folder: str, options: dict[str, Any]) -> dict[str, Any]:
        if not folder or "\x00" in folder:
            raise ContractError("Choose a source folder first")
        root = Path(folder).absolute()
        paths = source_paths(root, options)
        if len(paths) > 2000:
            raise ContractError("Scan supports at most 2000 images per source folder")
        result: dict[str, Any] = {}
        seen: set[tuple[int, int]] = set()
        budget, deadline = 256 * 1024 * 1024, time.monotonic() + 90
        for path in paths:
            if time.monotonic() > deadline:
                raise ContractError("Scan time limit reached; choose a smaller folder")
            info = path.lstat()
            identity = (info.st_dev, info.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            budget -= min(info.st_size, options["max_bytes"])
            if budget < 0:
                raise ContractError("Scan byte budget reached; choose a smaller folder")
            key = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
            result[key] = self._item(path, root, options["max_bytes"])
        return result

    def _item(self, path: Path, root: Path, limit: int) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path": str(path),
            "relative": str(path.relative_to(root)),
            "root": str(root),
            "status": "available",
            "sha256": "",
        }
        try:
            raw, info = read_source(path, limit)
            result.update(image_metadata(raw), size=info.st_size, mtime_ns=info.st_mtime_ns)
        except (OSError, ContractError):
            result.update(
                status="invalid", error="Unreadable, changed, unsupported or oversized image"
            )
        return result


def reconcile(previous: dict[str, Any], scanned: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(scanned)
    for key, old in previous.items():
        if key not in result:
            result[key] = {**deepcopy(old), "status": "missing"}
        elif old["sha256"] and old["sha256"] != result[key]["sha256"]:
            result[key]["status"] = "changed"
    return result
