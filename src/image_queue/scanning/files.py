"""Read-only bounded filesystem enumeration; links/junctions and generated files excluded."""

import os
import re
import stat
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from image_queue.domain.validation import ContractError

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
GENERATED = re.compile(r"_AI(?:_\d+)?$", re.IGNORECASE)


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def source_paths(root: Path, options: dict[str, Any]) -> list[Path]:
    if is_link(root) or not root.is_dir():
        raise ContractError("Source must be a real directory, not a link/junction")
    output = Path(options["output_folder"]).resolve() if options["output_folder"] else None
    if output is not None and (output == root.resolve() or output in root.resolve().parents):
        raise ContractError("Output folder must not contain the source root")
    deadline = time.monotonic() + 10
    return _walk(root, output, bool(options["recursive"]), deadline)


def _walk(root: Path, output: Path | None, recursive: bool, deadline: float) -> list[Path]:
    pending, result = [root], []
    visited = 0
    while pending:
        directory = pending.pop()
        for path, is_directory in _entries(directory, output, deadline):
            visited += 1
            if visited > 20000 or time.monotonic() > deadline:
                raise ContractError("Scan limit reached; choose a smaller source folder")
            if is_directory and recursive:
                pending.append(path)
            elif not is_directory and _supported(path):
                result.append(path)
    return sorted(result)


def _supported(path: Path) -> bool:
    return path.suffix.lower() in EXTENSIONS and not GENERATED.search(path.stem)


def _entries(directory: Path, output: Path | None, deadline: float) -> Iterator[tuple[Path, bool]]:
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index > 20000 or time.monotonic() > deadline:
                raise ContractError("Scan traversal limit reached")
            path = Path(entry.path)
            if is_link(path) or path.resolve() == output:
                continue
            if entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False):
                yield path, entry.is_dir(follow_symlinks=False)
