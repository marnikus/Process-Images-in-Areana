from pathlib import Path
import os
import tempfile

def get_output_path(source_path: Path, suffix: str = "_AI", opts: dict | None = None) -> Path:
    """
    Save output beside source as <base>_AI.<ext>
    - Never overwrite source (different name ensures)
    - If target exists and overwrite disabled, create unique name like name_AI_2.png
    - Preserve actual downloaded image format when practical
    opts: preserve_format (True), overwrite (False), downloaded_ext (None),
          unique_template ("{base}_AI_{n}{ext}")
    """
    o = opts or {}
    source_path = Path(source_path)
    base = source_path.stem
    ext = _output_ext(source_path, o.get("downloaded_ext"), o.get("preserve_format", True))
    target = source_path.parent / f"{base}{suffix}{ext}"
    if not target.exists() or o.get("overwrite", False):
        return target
    o.update({"parent": source_path.parent, "base": base, "ext": ext, "suffix": suffix})
    return _unique_output_path(o)


def _output_ext(source_path: Path, downloaded_ext: str | None, preserve_format: bool) -> str:
    """Output extension: downloaded format when preserved, else source's."""
    if downloaded_ext and preserve_format:
        # Ensure leading dot
        return downloaded_ext if downloaded_ext.startswith(".") else f".{downloaded_ext}"
    return source_path.suffix


def _unique_output_path(o: dict) -> Path:
    """First free name per template (name_AI_2.png style); cap at 1000.
    o: parent, base, ext, suffix, unique_template."""
    parent, base, ext, suffix = o["parent"], o["base"], o["ext"], o["suffix"]
    template = o.get("unique_template", "{base}_AI_{n}{ext}")
    n = 2
    while True:
        # Try template
        try:
            name = template.format(base=base, n=n, ext=ext)
        except Exception:
            name = f"{base}{suffix}_{n}{ext}"
        candidate = parent / name
        if not candidate.exists():
            return candidate
        n += 1
        if n > 1000:
            raise RuntimeError("Too many existing output files, cannot create unique name")


def atomic_write_bytes(temp_dir: Path, final_path: Path, data: bytes) -> Path:
    """
    Write to temporary partial file first, validate it, then rename atomically to final.
    Returns final_path.
    """
    final_path = Path(final_path)
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory as final for atomic rename (same filesystem)
    # Use tempfile in final_path.parent
    fd, tmp_path_str = tempfile.mkstemp(prefix=final_path.stem + ".partial_", suffix=final_path.suffix, dir=str(final_path.parent))
    tmp_path = Path(tmp_path_str)
    try:
        os.write(fd, data)
        os.close(fd)
        # Validate basic: non-empty
        if len(data) == 0:
            raise ValueError("Empty data")
        # Atomic rename
        tmp_path.replace(final_path)
    finally:
        # Cleanup if still exists
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
    return final_path

def is_ai_generated_filename(path: Path, suffix: str = "_AI") -> bool:
    """Ignore generated output files by default so files ending in _AI are not processed."""
    import re
    stem = Path(path).stem
    # Exact suffix at end
    if stem.endswith(suffix):
        return True
    # Suffix + _<number> at end, e.g., _AI_2, _AI_10
    pattern = re.escape(suffix) + r"_\d+$"
    if re.search(pattern, stem):
        return True
    return False
