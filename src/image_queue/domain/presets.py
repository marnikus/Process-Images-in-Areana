"""Strict versioned connection preset codec; pure JSON conversion, not a disk store."""

import json
from dataclasses import asdict

from image_queue.domain.settings import ChromeEndpoint, ConnectionPreset, HighlightSettings
from image_queue.domain.urls import UrlRow
from image_queue.domain.validation import (
    ContractError,
    require_boolean,
    require_fields,
    require_integer,
    require_text,
)

FORMAT = "image-queue/connection-preset"
SCHEMA_VERSION = 1
MAX_PRESET_BYTES = 1_048_576


def dumps_preset(preset: ConnectionPreset) -> str:
    payload = {"format": FORMAT, "schema_version": SCHEMA_VERSION, **asdict(preset)}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _check_size(text)
    return text


def loads_preset(text: str) -> ConnectionPreset:
    """Reject duplicate JSON keys, unsupported versions and unexpected saved fields."""
    _check_size(text)
    try:
        raw = json.loads(text, object_pairs_hook=_unique_keys)
    except (ValueError, RecursionError) as exc:
        raise ContractError("preset: malformed JSON or duplicate keys") from exc
    data = require_fields(
        raw, {"format", "schema_version", "endpoint", "highlight", "urls"}, "preset"
    )
    if data["format"] != FORMAT:
        raise ContractError("preset: unsupported format; use an explicit compatibility import")
    require_integer(data["schema_version"], (SCHEMA_VERSION, SCHEMA_VERSION), "schema_version")
    return ConnectionPreset(
        _endpoint(data["endpoint"]), _highlight(data["highlight"]), _rows(data["urls"])
    )


def _check_size(text: str) -> None:
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError as exc:
        raise ContractError("preset: invalid Unicode text") from exc
    if size > MAX_PRESET_BYTES:
        raise ContractError("preset: exceeds 1 MiB limit")


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("preset: duplicate JSON keys")
        result[key] = value
    return result


def _endpoint(value: object) -> ChromeEndpoint:
    data = require_fields(value, {"host", "port"}, "endpoint")
    return ChromeEndpoint(
        require_text(data["host"], "host"), require_integer(data["port"], (1, 65535), "port")
    )


def _highlight(value: object) -> HighlightSettings:
    names = {"highlight_enabled", "confirm_pause_ms", "highlight_ms"}
    data = require_fields(value, names, "highlight")
    return HighlightSettings(
        require_boolean(data["highlight_enabled"], "highlight_enabled"),
        require_integer(data["confirm_pause_ms"], (0, 30000), "confirm_pause_ms"),
        require_integer(data["highlight_ms"], (0, 30000), "highlight_ms"),
    )


def _rows(value: object) -> tuple[UrlRow, ...]:
    if not isinstance(value, list):
        raise ContractError("urls: expected a list")
    return tuple(_row(item) for item in value)


def _row(value: object) -> UrlRow:
    data = require_fields(value, {"row_id", "exact_url", "enabled"}, "URL row")
    return UrlRow(
        require_text(data["row_id"], "row_id"),
        require_text(data["exact_url"], "exact_url"),
        require_boolean(data["enabled"], "enabled"),
    )
