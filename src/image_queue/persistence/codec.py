"""Checksummed JSON snapshots with strict schema, duplicate-key and size validation."""

import hashlib
import json
from typing import Any, cast

from image_queue.domain.validation import ContractError, require_fields
from image_queue.workspace.history import validate_state

MAX_STATE_BYTES = 32 * 1024 * 1024


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise ContractError("state: duplicate JSON key")
        data[key] = value
    return data


def _canonical(state: Any) -> bytes:
    try:
        return json.dumps(
            state, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ContractError("state: cannot serialize invalid data") from exc


def encode_state(state: dict[str, Any]) -> bytes:
    validate_state(state)
    digest = hashlib.sha256(_canonical(state)).hexdigest()
    data = _canonical({"format": "image-queue/workspace", "sha256": digest, "state": state})
    if len(data) > MAX_STATE_BYTES:
        raise ContractError("state: exceeds 32 MiB safety limit")
    return data


def decode_state(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_STATE_BYTES:
        raise ContractError("state: exceeds 32 MiB safety limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError("state: invalid JSON; recovery required") from exc
    data = require_fields(value, {"format", "sha256", "state"}, "state envelope")
    if data["format"] != "image-queue/workspace":
        raise ContractError("state: unsupported format")
    if data["sha256"] != hashlib.sha256(_canonical(data["state"])).hexdigest():
        raise ContractError("state: checksum mismatch; recovery required")
    validate_state(data["state"])
    return dict(cast(dict[str, Any], data["state"]))  # validated object; caller owns a fresh copy
