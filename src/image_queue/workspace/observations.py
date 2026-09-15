"""Strict scanner records, separate from editable selection and future attempt evidence."""

import re
from typing import Any

from image_queue.domain.validation import ContractError, require_integer

BASE = {"path", "relative", "root", "status", "sha256"}
IMAGE = {"width", "height", "format", "thumbnail", "size", "mtime_ns"}


def validate_sources(sources: Any) -> None:
    if not isinstance(sources, dict) or len(sources) > 10000:
        raise ContractError("Too many source observations or invalid source map")
    for key, source in sources.items():
        if not isinstance(key, str) or not re.fullmatch("[0-9a-f]{64}", key):
            raise ContractError("Invalid source record ID")
        _validate_source(source)


def _validate_source(source: Any) -> None:
    if not isinstance(source, dict) or not BASE <= set(source) <= BASE | IMAGE | {"error"}:
        raise ContractError("Invalid source record fields")
    if source["status"] not in ("available", "changed", "invalid", "missing"):
        raise ContractError("Scanner observations cannot fabricate completion")
    _texts(source)
    if source["sha256"]:
        if not re.fullmatch("[0-9a-f]{64}", source["sha256"]):
            raise ContractError("Invalid source SHA-256")
        _image(source)
    elif source["status"] not in ("invalid", "missing"):
        raise ContractError("Available source requires a fingerprint")


def _image(source: dict[str, Any]) -> None:
    if not IMAGE <= set(source):
        raise ContractError("Missing image observation metadata")
    require_integer(source["width"], (1, 40_000_000), "image width")
    require_integer(source["height"], (1, 40_000_000), "image height")
    require_integer(source["size"], (1, 64 * 1024 * 1024), "image byte size")
    require_integer(source["mtime_ns"], (-(2**63), 2**63 - 1), "image mtime")
    thumbnail = source["thumbnail"]
    if not isinstance(thumbnail, str) or len(thumbnail) > 20000:
        raise ContractError("Invalid thumbnail")
    if not re.fullmatch(r"data:image/jpeg;base64,[A-Za-z0-9+/=]+", thumbnail):
        raise ContractError("Thumbnail must be a local JPEG data URL")


def _texts(source: dict[str, Any]) -> None:
    for name in ("path", "relative", "root", "sha256"):
        if not isinstance(source[name], str) or len(source[name]) > 64000 or "\x00" in source[name]:
            raise ContractError("Invalid source record text")
