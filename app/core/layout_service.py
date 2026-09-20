"""LayoutService — C5 refactor with predicate table and small helpers."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.core.window_catalog import (  # noqa: F401 — the one window table (S8); re-exported for callers
    GRID_VERSION,
    LEGACY_WINDOW_IDS,
    WINDOW_IDS,
    WINDOW_TITLES,
    WINDOWS,
    default_grid_tree,
)

log = logging.getLogger("arena")
MIN_GRID_SIZE = 4


@dataclass
class GridSpec:
    """Param object for grid validation (C5)."""
    max_depth: int = 12
    min_size: float = MIN_GRID_SIZE


def default_payload() -> str:
    return json.dumps({"v": GRID_VERSION, "tree": default_grid_tree()},
                      ensure_ascii=False, separators=(",", ":"))


def _parse_one_size(s) -> float:
    try:
        n = float(s)
        return n if n > 0 else float(MIN_GRID_SIZE)
    except Exception:
        return float(MIN_GRID_SIZE)


def _scale_to_100(base: list[float]) -> list[float]:
    total = sum(base) or 1
    return [(s / total) * 100 for s in base]


def _redistribute_min(scaled: list[float], base: list[float]) -> list[float]:
    floor = MIN_GRID_SIZE * len(scaled)
    if floor >= 100:
        return [100 / len(scaled)] * len(scaled)
    excess = [max(0, s - MIN_GRID_SIZE) for s in base]
    excess_total = sum(excess) or 1
    remaining = 100 - floor
    return [MIN_GRID_SIZE + (e / excess_total) * remaining for e in excess]


def _normalize_sizes(sizes):
    base = [_parse_one_size(s) for s in sizes]
    scaled = _scale_to_100(base)
    if any(s < MIN_GRID_SIZE for s in scaled):
        return _redistribute_min(scaled, base)
    return scaled


def _check_depth(depth: int) -> tuple[dict | None, str | None]:
    if depth > 12:
        return None, "tree too deep"
    return None, None


def _normalize_leaf(node: dict) -> tuple[dict | None, str | None]:
    lid = node.get("id")
    if not isinstance(lid, str) or not lid:
        return None, "leaf without id"
    return {"t": "leaf", "id": lid}, None


def _check_dir(node: dict) -> str | None:
    if node.get("dir") not in ("row", "col"):
        return "bad dir"
    return None


def _check_children(kids) -> str | None:
    if not isinstance(kids, list) or len(kids) < 2:
        return "split needs >=2 children"
    return None


def _check_sizes_match(sizes, kids) -> str | None:
    if not isinstance(sizes, list) or len(sizes) != len(kids):
        return "sizes must match children"
    return None


def _normalize_size_list(sizes) -> tuple[list[float] | None, str | None]:
    clean = []
    for s in sizes:
        if isinstance(s, bool) or not isinstance(s, (int, float)) or s < MIN_GRID_SIZE:
            return None, "bad size value"
        clean.append(float(s))
    if not 99.5 <= sum(clean) <= 100.5:
        return None, "sizes must sum to 100"
    return clean, None


def _normalize_children(kids, depth: int) -> tuple[list | None, str | None]:
    clean_kids = []
    for kid in kids:
        c, err = normalize_grid_tree(kid, depth + 1)
        if err:
            return None, err
        clean_kids.append(c)
    return clean_kids, None


def _normalize_split(node, depth):
    """Validate + rebuild a split node; leaf dispatch stays in normalize_grid_tree."""
    err = _check_dir(node)
    if err:
        return None, err
    kids = node.get("children")
    sizes = node.get("sizes")
    err = _check_children(kids)
    if err:
        return None, err
    err = _check_sizes_match(sizes, kids)
    if err:
        return None, err
    clean_sizes, err = _normalize_size_list(sizes)
    if err:
        return None, err
    clean_kids, err = _normalize_children(kids, depth)
    if err:
        return None, err
    return {"t": "split", "dir": node["dir"], "children": clean_kids, "sizes": clean_sizes}, None


def normalize_grid_tree(node, depth=0):
    _, err = _check_depth(depth)
    if err:
        return None, err
    if not isinstance(node, dict):
        return None, "node must be object"
    t = node.get("t", node.get("type"))
    if t == "leaf":
        return _normalize_leaf(node)
    if t != "split":
        return None, "unknown node type"
    return _normalize_split(node, depth)


def leaf_ids(node, out=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        t = node.get("t", node.get("type"))
        if t == "leaf":
            out.append(node.get("id"))
        elif t == "split":
            for kid in node.get("children") or []:
                leaf_ids(kid, out)
    return out


def validate_grid_tree(node):
    _, err = normalize_grid_tree(node)
    return err


def parse_grid_payload(raw: str):
    try:
        data = json.loads(raw)
    except Exception as exc:
        return None, f"bad JSON ({exc})"
    if not isinstance(data, dict):
        return None, "payload must be object"
    v = data.get("v")
    if not isinstance(v, int) or not 1 <= v <= GRID_VERSION:
        return None, f"unsupported version {v!r}"
    tree, err = normalize_grid_tree(data.get("tree"))
    if err:
        return None, err
    got = sorted([i for i in leaf_ids(tree) if i])
    if got != sorted(WINDOW_IDS):
        return None, "window set mismatch"
    return tree, None


def _try_migrate(raw: str, err: str):
    if err not in ("window set mismatch", "leaf count mismatch") and not err.startswith("leaf id mismatch"):
        return None, err
    try:
        data = json.loads(raw)
        raw_tree = data.get("tree") if isinstance(data, dict) and "tree" in data else data
        if isinstance(raw_tree, dict):
            migrated = migrate_grid_tree(raw_tree)
            m_tree, m_err = parse_grid_payload(json.dumps({"v": GRID_VERSION, "tree": migrated}))
            if not m_err:
                return json.dumps({"v": GRID_VERSION, "tree": m_tree},
                                  ensure_ascii=False, separators=(",", ":")), None
            log.warning(f"Migration still failed after window mismatch: {m_err}, rejecting")
            return None, m_err or err
    except Exception as e:
        log.warning(f"Failed to migrate grid after mismatch {err}: {e}, rejecting")
        return None, err
    return None, err


def canonical_grid_payload(raw: str):
    tree, err = parse_grid_payload(raw)
    if err:
        migrated, m_err = _try_migrate(raw, err)
        if migrated:
            return migrated, None
        if m_err and m_err != err:
            return None, m_err
        return None, err
    return json.dumps({"v": GRID_VERSION, "tree": tree},
                      ensure_ascii=False, separators=(",", ":")), None


def _rename_legacy_windows(node):
    """Rewrite renamed window ids in a stored tree (identity elsewhere)."""
    if not isinstance(node, dict):
        return node
    t = node.get("t", node.get("type"))
    if t == "leaf":
        new_id = LEGACY_WINDOW_IDS.get(node.get("id"))
        return {**node, "id": new_id} if new_id else node
    if t == "split" and isinstance(node.get("children"), list):
        kids = [_rename_legacy_windows(k) for k in node["children"]]
        if all(new is old for new, old in zip(kids, node["children"])):
            return node  # nothing renamed: the stored tree keeps its identity
        return {**node, "children": kids}
    return node


def migrate_grid_tree(tree: dict) -> dict:
    tree = _rename_legacy_windows(tree)
    present = {i for i in leaf_ids(tree) if i}
    missing = [i for i in sorted(WINDOW_IDS) if i not in present]
    if not missing:
        return tree
    if len(missing) == 1:
        extra = {"t": "leaf", "id": missing[0]}
    else:
        share = round(100 / len(missing), 4)
        sizes = [share] * len(missing)
        sizes[0] = round(100 - share * (len(missing) - 1), 4)
        extra = {"t": "split", "dir": "row",
                 "children": [{"t": "leaf", "id": i} for i in missing], "sizes": sizes}
    room = min(40, max(MIN_GRID_SIZE, len(missing) * 9))
    return {"t": "split", "dir": "col", "children": [tree, extra], "sizes": [100 - room, room]}


def node_type(node):
    return node.get("t", node.get("type")) if isinstance(node, dict) else None
