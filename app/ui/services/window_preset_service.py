"""Window-preset documents — pure parse/build/validate (no Qt/signals).

Owns the portable-doc <-> grid-tree conversions plus save/load document
shaping. Panels pass plain data in and persist the returned doc.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from app.core.layout_service import GRID_VERSION, canonical_grid_payload, leaf_ids


def extract_tree_from_grid(g: dict, parsed: dict):
    """Tree case: validate embedded tree, return (tree, payload)."""
    if "tree" not in g or not isinstance(g["tree"], dict):
        return None, None
    tree = g["tree"]
    ver = g.get("version") or parsed.get("v") or 4
    cand = json.dumps({"v": ver, "tree": tree}, ensure_ascii=False, separators=(",", ":"))
    tp, err = canonical_grid_payload(cand)
    if err:
        return None, None
    return tree, tp


def extract_payload_from_grid(g: dict):
    """Payload case: validate embedded payload string, return (tree, payload)."""
    if "payload" not in g or not isinstance(g["payload"], str):
        return None, None
    tp, err = canonical_grid_payload(g["payload"])
    if err:
        return None, None
    data = json.loads(tp)
    return data.get("tree"), tp


def extract_from_portable(parsed: dict):
    """Portable doc -> (tree, payload, window_states, doc) or Nones."""
    try:
        if not isinstance(parsed, dict):
            return None, None, None, None
        if "grid" not in parsed or not isinstance(parsed["grid"], dict):
            return None, None, None, None
        g = parsed["grid"]
        ws = parsed.get("window_states")
        tree, payload = extract_tree_from_grid(g, parsed)
        if payload:
            return tree, payload, ws, parsed
        tree, payload = extract_payload_from_grid(g)
        if payload:
            return tree, payload, ws, parsed
        return None, None, None, None
    except Exception:
        return None, None, None, None


def parse_preset_input(grid_json: str):
    """Accept portable doc / raw {v,tree} / legacy; return (tree, payload, ws, doc, err)."""
    if not grid_json:
        return None, None, None, None, None
    try:
        parsed = json.loads(grid_json)
    except Exception as e:
        return None, None, None, None, f"bad JSON {e}"
    if not isinstance(parsed, dict):
        return None, None, None, None, "payload must be object"
    tree, payload, ws, doc = extract_from_portable(parsed)
    if payload:
        return tree, payload, ws, doc, None
    return _raw_tree_result(parsed, grid_json)


def _raw_tree_result(parsed, grid_json):
    """Raw {v,tree} input -> (tree, payload, ws, doc, err); Nones when N/A."""
    if "v" in parsed and "tree" in parsed:
        tp, err = canonical_grid_payload(grid_json)
        if not err:
            data = json.loads(tp)
            return data.get("tree"), tp, None, None, None
        return None, None, None, None, err
    return None, None, None, None, None


def _preset_ws(info: dict, stored_ws: dict) -> dict:
    """Incoming ws wins, else stored; never None."""
    ws = info.get("ws")
    if ws:
        return ws
    ws = stored_ws or {"closed": [], "minimized": []}
    incoming = info.get("incoming")
    if incoming and isinstance(incoming.get("window_states"), dict):
        ws = incoming["window_states"]
    return ws


def _wrap_incoming(name: str, payload: str, info: dict) -> dict:
    """Refresh a portable envelope around the validated tree."""
    tree, ws, incoming = info.get("tree"), info.get("ws"), info.get("incoming")
    data = json.loads(payload)
    count = len(leaf_ids(tree)) if tree else 0
    doc = incoming.copy()
    doc["name"] = name
    doc["grid"] = {"payload": payload, "window_count": count, "tree": tree,
                   "type": doc.get("grid", {}).get("type", "sash-tree"),
                   "version": data.get("v", 4), "sizes_unit": "percent"}
    doc["window_states"] = ws
    doc["updated_at"] = datetime.utcnow().isoformat() + "Z"
    doc["app_version"] = doc.get("app_version", "arena-1.0")
    return doc


def build_preset_doc(name: str, payload: str, info: dict) -> dict:
    """Final preset document from validated payload + info dict."""
    tree = info.get("tree") or json.loads(payload).get("tree")
    ws = _preset_ws(info, info.get("stored_ws"))
    incoming = info.get("incoming")
    if incoming and isinstance(incoming, dict) and incoming.get("format") == "chat-v-bot.window-preset":
        resolved = {"tree": tree, "ws": ws, "incoming": incoming}
        return _wrap_incoming(name, payload, resolved)
    return {"name": name,
            "grid": {"payload": payload, "window_count": len(leaf_ids(tree)) if tree else 0,
                     "tree": tree},
            "window_states": ws, "updated_at": datetime.utcnow().isoformat() + "Z",
            "app_version": "arena-1.0"}


def save_preset_doc(name: str, grid_json: str, layout_fallback: str, stored_ws: dict):
    """Validate input (or fallback layout) and build the doc to persist.

    Returns (doc, error): exactly one is None. Caller persists + emits.
    """
    tree, payload, ws, incoming, err = parse_preset_input(grid_json)
    if not payload:
        payload, err = canonical_grid_payload(layout_fallback or "")
    if err and not payload:
        return None, err
    if not payload:
        return None, "invalid grid payload"
    info = {"tree": tree, "ws": ws, "incoming": incoming, "stored_ws": stored_ws}
    return build_preset_doc(name, payload, info), None


def load_preset_doc(doc: Optional[dict], name: str):
    """Validate a stored preset for the JS preview flow.

    Returns (payload_json, error): payload is the portable doc JSON.
    """
    if not doc:
        return None, f"preset {name} not found"
    try:
        grid = doc.get("grid", {})
        tree = grid.get("tree") if isinstance(grid, dict) else None
        if not isinstance(tree, dict):
            return None, "unsupported window preset format or schema version"
        ver = grid.get("version", GRID_VERSION)
        _, err = canonical_grid_payload(json.dumps({"v": ver, "tree": tree}))
        if err:
            return None, err
        return json.dumps(doc, ensure_ascii=False), None
    except Exception as e:
        return None, str(e)
