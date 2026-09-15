"""Local original-byte validation and no-clobber publication; no network downloader."""

import os
import tempfile
from pathlib import Path

from image_queue.domain.validation import ContractError
from image_queue.persistence.atomic import sync_directory
from image_queue.scanning.images import image_metadata, read_source

LIMIT = 64 * 1024 * 1024
EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff"}


def inspect_output(content: bytes) -> tuple[str, str]:
    if not isinstance(content, bytes) or not 0 < len(content) <= LIMIT:
        raise ContractError("Output exceeds the bounded image-byte contract")
    metadata = image_metadata(content)
    return EXTENSIONS[metadata["format"]], str(metadata["sha256"])


def destination(folder: Path, source: Path, extension: str) -> Path:
    if not folder.is_dir() or folder.is_symlink():
        raise ContractError("Choose an existing trusted local output directory")
    if bool(getattr(folder.lstat(), "st_file_attributes", 0) & 0x400):
        raise ContractError("Output reparse points are not supported")
    folder = folder.resolve(strict=True)
    stem = source.stem[:100]
    for number in range(1, 10001):
        suffix = "" if number == 1 else f"_{number}"
        candidate = folder / f"{stem}_AI{suffix}{extension}"
        if not os.path.lexists(candidate) and candidate != source.resolve():
            return candidate
    raise ContractError("Output collision limit reached")


def verify_file(path: Path, digest: str) -> None:
    content, _ = read_source(path, LIMIT)
    extension, actual = inspect_output(content)
    if actual != digest or path.suffix != extension:
        raise ContractError("Published output differs from durable evidence")


def publish(path: Path, content: bytes, digest: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".image-", suffix=".partial", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # link is atomic create-if-absent. Never fall back to replace or copying a partial file.
        os.link(temporary, path)
        sync_directory(path.parent)
        verify_file(path, digest)
    finally:
        temporary.unlink(missing_ok=True)
