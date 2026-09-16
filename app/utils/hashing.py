import hashlib
from pathlib import Path

def file_sha256(path: Path, chunk_size: int = 8192) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def fingerprint_from_path_stat(relative_path: str, size: int, mtime: float) -> str:
    """Durable identifier based on path + metadata."""
    raw = f"{relative_path}|{size}|{mtime}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
