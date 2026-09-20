"""Naming — output path with OutputSpec param object (C5).

RULE18: file 150-300, func ≤20, CC≤10, params≤4, predicate table.
"""
from __future__ import annotations

import functools
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

AI_SUFFIX = "_AI"  # the one literal: outputs, the scan filter and Drop _AI all read it


@dataclass
class OutputSpec:
    """Param object for get_output_path (C5)."""
    suffix: str = AI_SUFFIX
    preserve_format: bool = True
    overwrite: bool = False
    downloaded_ext: str | None = None
    unique_template: str = "{base}_AI_{n}{ext}"


@dataclass
class ImageSpec:
    """Param object for image handling."""
    base: str
    ext: str
    parent: Path


def _resolve_ext(source_ext: str, spec: OutputSpec) -> str:
    if spec.downloaded_ext and spec.preserve_format:
        ext = spec.downloaded_ext
        return ext if ext.startswith(".") else f".{ext}"
    return source_ext


def _build_target_path(image_spec: ImageSpec, spec: OutputSpec) -> Path:
    return image_spec.parent / f"{image_spec.base}{spec.suffix}{image_spec.ext}"


def _build_unique_candidate(image_spec: ImageSpec, spec: OutputSpec, n: int) -> Path:
    try:
        name = spec.unique_template.format(base=image_spec.base, n=n, ext=image_spec.ext)
    except Exception:
        name = f"{image_spec.base}{spec.suffix}_{n}{image_spec.ext}"
    return image_spec.parent / name


def _find_unique_path(image_spec: ImageSpec, spec: OutputSpec) -> Path:
    n = 2
    while True:
        candidate = _build_unique_candidate(image_spec, spec, n)
        if not candidate.exists():
            return candidate
        n += 1
        if n > 1000:
            raise RuntimeError("Too many existing output files, cannot create unique name")


def get_output_path(source_path: Path, spec: OutputSpec = None) -> Path:
    if spec is None:
        spec = OutputSpec()
    source_path = Path(source_path)
    ext = _resolve_ext(source_path.suffix, spec)
    img_spec = ImageSpec(base=source_path.stem, ext=ext, parent=source_path.parent)
    target = _build_target_path(img_spec, spec)
    if not target.exists() or spec.overwrite:
        return target
    return _find_unique_path(img_spec, spec)


def atomic_write_bytes(temp_dir: Path, final_path: Path, data: bytes) -> Path:
    final_path = Path(final_path)
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=final_path.stem + ".partial_", suffix=final_path.suffix, dir=str(final_path.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        os.write(fd, data)
        os.close(fd)
        if len(data) == 0:
            raise ValueError("Empty data")
        tmp_path.replace(final_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
    return final_path


@functools.lru_cache(maxsize=8)
def _ai_family_re(suffix: str) -> re.Pattern:
    """`<base><suffix>` or `<base><suffix>_<n>` — the family `get_output_path` writes."""
    return re.compile(rf"^(?P<base>.*){re.escape(suffix)}(?:_(?P<n>\d+))?$")


def parse_ai_output(stem: str, suffix: str = AI_SUFFIX) -> tuple[str, int | None] | None:
    """(base, counter) of an output stem — `photo_AI` → ("photo", None), `photo_AI_3` → ("photo", 3); None for a source."""
    m = _ai_family_re(suffix).match(stem)
    if m is None:
        return None
    n = m.group("n")
    return m.group("base"), (int(n) if n is not None else None)


def is_ai_generated_filename(path: Path, suffix: str = AI_SUFFIX) -> bool:
    return parse_ai_output(Path(path).stem, suffix) is not None
