"""Strict editable workspace schema, separate from runtime jobs and durable undo metadata."""

from copy import deepcopy
from typing import Any

from image_queue.domain.presets import dumps_preset, loads_preset
from image_queue.domain.settings import ConnectionPreset
from image_queue.domain.validation import ContractError, require_fields, require_text
from image_queue.workspace.extensions import defaults, validate_extensions
from image_queue.workspace.layout import validate_layout

FIELDS = {"layout", "prompt", "folder", "connection", "layouts", "geometry"}


def default_workspace(tree: dict[str, Any]) -> dict[str, Any]:
    workspace = {
        "layout": {
            "tree": deepcopy(tree),
            "closed": [
                "filters",
                "history",
                "userdb",
                "collector",
                "labels",
                "botchat",
                "botprompt",
                "stats",
            ],
            "minimized": [],
        },
        "prompt": "",
        "folder": "",
        "connection": dumps_preset(ConnectionPreset()),
        "layouts": {},
        "geometry": [80, 80, 1440, 960],
    }
    workspace.update(defaults())
    validate_workspace(workspace)
    return workspace


def validate_workspace(value: Any) -> None:
    expected = (
        FIELDS | set(defaults()) if isinstance(value, dict) and set(value) != FIELDS else FIELDS
    )
    data = require_fields(value, expected, "workspace")
    validate_extensions({**defaults(), **data})
    validate_layout(data["layout"])
    for name in ("prompt", "folder"):
        text = require_text(data[name], name)
        if len(text) > 64000 or "\x00" in text:
            raise ContractError(f"{name}: excessive length or NUL character")
    loads_preset(require_text(data["connection"], "connection"))
    _validate_layouts(data["layouts"])
    _validate_geometry(data["geometry"])


def _validate_layouts(value: Any) -> None:
    if not isinstance(value, dict) or len(value) > 30:
        raise ContractError("layouts: at most 30 named layouts supported")
    for name, layout in value.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ContractError("layouts: name must be 1–80 nonempty characters")
        validate_layout(layout)


def _validate_geometry(value: Any) -> None:
    if not isinstance(value, list) or len(value) != 4:
        raise ContractError("geometry: expected x/y/width/height")
    if any(type(item) is not int or abs(item) > 100000 for item in value):
        raise ContractError("geometry: bounded integers required")
    if not (800 <= value[2] <= 10000 and 600 <= value[3] <= 10000):
        raise ContractError("geometry: window dimensions outside supported range")
