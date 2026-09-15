"""Validate the retained sash-tree wire format; stable panel IDs, no implicit migration."""

from typing import Any

from image_queue.domain.validation import ContractError, require_fields

PANEL_IDS = frozenset(
    {
        "stats",
        "filters",
        "stack",
        "config",
        "composer",
        "people",
        "log",
        "history",
        "userdb",
        "collector",
        "labels",
        "dbconn",
        "botchat",
        "botprompt",
    }
)


def validate_tree(tree: Any) -> None:
    ids = _node_ids(tree, 0)
    if len(ids) != len(PANEL_IDS) or set(ids) != PANEL_IDS:
        raise ContractError("layout: every registered window must occur exactly once")


def _node_ids(node: Any, depth: int) -> list[str]:
    if depth > 12 or not isinstance(node, dict):
        raise ContractError("layout: invalid node or excessive nesting")
    if node.get("t") == "leaf":
        return [_leaf_id(node)]
    split = require_fields(node, {"t", "dir", "children", "sizes"}, "split")
    if split["t"] != "split" or split["dir"] not in ("row", "col"):
        raise ContractError("layout: invalid split direction/type")
    children = split["children"]
    if not isinstance(children, list) or not 2 <= len(children) <= len(PANEL_IDS):
        raise ContractError("layout: split needs 2–14 children")
    _validate_sizes(split["sizes"], len(children))
    return [item for child in children for item in _node_ids(child, depth + 1)]


def _leaf_id(node: Any) -> str:
    leaf = require_fields(node, {"t", "id"}, "leaf")
    if not isinstance(leaf["id"], str) or leaf["id"] not in PANEL_IDS:
        raise ContractError("layout: unknown window; explicit mapping required")
    return leaf["id"]


def _validate_sizes(sizes: Any, count: int) -> None:
    if not isinstance(sizes, list) or len(sizes) != count:
        raise ContractError("layout: sizes must correspond to children")
    if any(type(size) not in (int, float) or not 4 <= size <= 100 for size in sizes):
        raise ContractError("layout: finite percentages of at least 4 required")
    if abs(sum(sizes) - 100) > 0.01:
        raise ContractError("layout: percentages must sum to 100")


def validate_layout(value: Any) -> None:
    data = require_fields(value, {"tree", "closed", "minimized"}, "layout")
    validate_tree(data["tree"])
    closed = _window_set(data["closed"])
    minimized = _window_set(data["minimized"])
    if closed & minimized:
        raise ContractError("layout: closed and minimized windows cannot overlap")


def _window_set(value: Any) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContractError("layout: window IDs must be a list of strings")
    result = set(value)
    if not result <= PANEL_IDS or len(result) != len(value):
        raise ContractError("layout: unknown or duplicate window IDs")
    return result
