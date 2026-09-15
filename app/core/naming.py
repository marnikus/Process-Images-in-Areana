from pathlib import Path
import os
import tempfile

def get_output_path(
    source_path: Path,
    suffix: str = "_AI",
    preserve_format: bool = True,
    overwrite: bool = False,
    downloaded_ext: str | None = None,
    unique_template: str = "{base}_AI_{n}{ext}"
) -> Path:
    """
    Save output beside source as <base>_AI.<ext>
    - Never overwrite source (different name ensures)
    - If target exists and overwrite disabled, create unique name like name_AI_2.png
    - Preserve actual downloaded image format when practical
    """
    source_path = Path(source_path)
    if downloaded_ext and preserve_format:
        # Ensure leading dot
        ext = downloaded_ext if downloaded_ext.startswith(".") else f".{downloaded_ext}"
    else:
        ext = source_path.suffix

    base = source_path.stem
    # If base already ends with _AI, keep it? But we add suffix anyway — spec says ignore _AI outputs by default, so source shouldn't be _AI.
    # However if source is "image_AI", output would be "image_AI_AI" — that's okay, avoids loop.
    target = source_path.parent / f"{base}{suffix}{ext}"

    if not target.exists() or overwrite:
        return target

    # Create unique name
    n = 2
    while True:
        # Try template
        try:
            name = unique_template.format(base=base, n=n, ext=ext)
        except Exception:
            name = f"{base}{suffix}_{n}{ext}"
        candidate = source_path.parent / name
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
