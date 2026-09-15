"""Validated immutable attempt inputs, including exact marker text and highlight settings."""

import re
from typing import Any

from image_queue.domain.settings import HighlightSettings
from image_queue.domain.urls import UrlRow
from image_queue.domain.validation import (
    ContractError,
    require_boolean,
    require_fields,
    require_integer,
)
from image_queue.workspace.variables import render_prompt


def validate_inputs(inputs: dict[str, Any]) -> None:
    identifier = inputs["id"]
    if not isinstance(identifier, str) or not re.fullmatch("[0-9a-f]{32}", identifier):
        raise ContractError("Invalid attempt identifier")
    UrlRow(inputs["row_id"], inputs["url"])
    highlight = require_fields(
        inputs["highlight"],
        {"highlight_enabled", "highlight_ms", "confirm_pause_ms"},
        "attempt highlight",
    )
    HighlightSettings(
        require_boolean(highlight["highlight_enabled"], "highlight"),
        require_integer(highlight["confirm_pause_ms"], (0, 30000), "confirm"),
        require_integer(highlight["highlight_ms"], (0, 30000), "duration"),
    )
    rendered = render_prompt(inputs["raw_prompt"], inputs["variables"], inputs["mode"])
    if not rendered["ok"] or inputs["text"] != f"[JOB-ID:{identifier}]\n" + rendered["text"]:
        raise ContractError("Immutable prompt differs from its variable snapshot/marker")
    _source(inputs["source"])
    _baseline(inputs["baseline"])


def _source(source: Any) -> None:
    data = require_fields(source, {"id", "sha256", "path", "name"}, "attempt source")
    for name in ("id", "sha256"):
        value = data[name]
        if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
            raise ContractError("Invalid source identity/fingerprint")
    for name in ("path", "name"):
        value = data[name]
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ContractError("Invalid source path/name")


def _baseline(baseline: Any) -> None:
    data = require_fields(baseline, {"target", "context", "messages", "responses"}, "baseline")
    for name in ("target", "context"):
        if not isinstance(data[name], str) or not data[name]:
            raise ContractError("Baseline requires target/context identity")
    for name in ("messages", "responses"):
        _identifiers(data[name])


def _identifiers(values: Any) -> None:
    if not isinstance(values, list) or len(values) > 100:
        raise ContractError("Invalid or oversized baseline identities")
    if any(not isinstance(value, str) or not value for value in values):
        raise ContractError("Invalid baseline identity")
    if len(values) != len(set(values)):
        raise ContractError("Ambiguous baseline identities")
