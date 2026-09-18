"""LayoutService for Arena Image Processor — grid layout persistence.

Based on Old App layout_service but with arena WINDOW_IDS.
"""

import json
import logging
from typing import Any

log = logging.getLogger("arena")

WINDOW_IDS = ["url_list", "folder", "queue", "prompt", "run", "progress", "watcher", "log", "settings", "captcha", "browser", "action_blocks", "block_config", "arena_presets", "recordings"]
WINDOWS = [
    {"id": "url_list", "title": "URL List"},
    {"id": "folder", "title": "Folder Picker"},
    {"id": "queue", "title": "Image Queue"},
    {"id": "prompt", "title": "Prompt Editor"},
    {"id": "run", "title": "Run Controls"},
    {"id": "progress", "title": "Progress"},
    {"id": "watcher", "title": "Watcher — Generation & Captcha"},
    {"id": "log", "title": "Activity Log"},
    {"id": "settings", "title": "Settings"},
    {"id": "captcha", "title": "Captcha — 2Captcha Control"},
    {"id": "browser", "title": "Browser Preview"},
    {"id": "action_blocks", "title": "Action Blocks — Stacking Jobs"},
    {"id": "block_config", "title": "Block Config — Security Check"},
    {"id": "arena_presets", "title": "Arena Presets"},
    {"id": "recordings", "title": "Recordings — Captcha Sessions"},
]
WINDOW_TITLES = {w["id"]: w["title"] for w in WINDOWS}
# Windows this app renamed. A stored layout that still uses one keeps its
# position + sizes under the new id (never rejected, never default-substituted).
LEGACY_WINDOW_IDS = {"captcha_records": "recordings"}
GRID_VERSION = 5
MIN_GRID_SIZE = 4

def default_grid_tree() -> dict:
    def leaf(i): return {"t": "leaf", "id": i}
    def split(d, kids, sizes): return {"t": "split", "dir": d, "children": kids, "sizes": sizes}
    return split("col", [
        split("row", [
            split("col", [leaf("url_list"), leaf("folder")], [55,45]),
            split("col", [leaf("prompt"), leaf("run"), leaf("settings"), leaf("captcha")], [40,22,26,12]),
        ], [60,40]),
        split("row", [
            leaf("queue"),
            split("col", [leaf("action_blocks"), leaf("block_config")], [55,45]),
            split("col", [leaf("browser"), leaf("arena_presets"), leaf("recordings"), leaf("progress"), leaf("watcher")], [24,20,20,18,18]),
        ], [45,35,20]),
        leaf("log"),
    ], [38,40,22])

def default_payload() -> str:
    return json.dumps({"v": GRID_VERSION, "tree": default_grid_tree()}, ensure_ascii=False, separators=(",",":"))

def _normalize_sizes(sizes):
    base = []
    for s in sizes:
        try:
            n = float(s)
            if n <= 0: n = MIN_GRID_SIZE
        except Exception:
            n = MIN_GRID_SIZE
        base.append(n)
    total = sum(base) or 1
    # scale to 100
    scaled = [(s/total)*100 for s in base]
    # enforce min
    # simple: if any < MIN, distribute
    if any(s < MIN_GRID_SIZE for s in scaled):
        floor = MIN_GRID_SIZE * len(scaled)
        if floor >= 100:
            return [100/len(scaled)]*len(scaled)
        excess = [max(0, s-MIN_GRID_SIZE) for s in base]
        excess_total = sum(excess) or 1
        remaining = 100 - floor
        return [MIN_GRID_SIZE + (e/excess_total)*remaining for e in excess]
    return scaled

def normalize_grid_tree(node, depth=0):
    if depth > 12:
        return None, "tree too deep"
    if not isinstance(node, dict):
        return None, "node must be object"
    t = node.get("t", node.get("type"))
    if t == "leaf":
        lid = node.get("id")
        if not isinstance(lid, str) or not lid:
            return None, "leaf without id"
        return {"t": "leaf", "id": lid}, None
    if t != "split":
        return None, "unknown node type"
    if node.get("dir") not in ("row","col"):
        return None, "bad dir"
    kids = node.get("children")
    sizes = node.get("sizes")
    if not isinstance(kids, list) or len(kids) < 2:
        return None, "split needs >=2 children"
    if not isinstance(sizes, list) or len(sizes) != len(kids):
        return None, "sizes must match children"
    clean_sizes = []
    for s in sizes:
        if isinstance(s, bool) or not isinstance(s, (int,float)) or s < MIN_GRID_SIZE:
            return None, "bad size value"
        clean_sizes.append(float(s))
    if not 99.5 <= sum(clean_sizes) <= 100.5:
        return None, "sizes must sum to 100"
    clean_kids = []
    for kid in kids:
        c, err = normalize_grid_tree(kid, depth+1)
        if err:
            return None, err
        clean_kids.append(c)
    return {"t":"split","dir":node["dir"],"children":clean_kids,"sizes":clean_sizes}, None

def leaf_ids(node, out=None):
    if out is None: out = []
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
    # check window set
    got = sorted([i for i in leaf_ids(tree) if i])
    if got != sorted(WINDOW_IDS):
        return None, "window set mismatch"
    return tree, None

def canonical_grid_payload(raw: str):
    tree, err = parse_grid_payload(raw)
    if err:
        # If error is window set mismatch / leaf count / id mismatch, try to migrate
        if err in ("window set mismatch", "leaf count mismatch") or err.startswith("leaf id mismatch"):
            try:
                data = json.loads(raw)
                raw_tree = data.get("tree") if isinstance(data, dict) and "tree" in data else data
                if isinstance(raw_tree, dict):
                    migrated = migrate_grid_tree(raw_tree)
                    # Re-validate migrated
                    m_tree, m_err = parse_grid_payload(json.dumps({"v": GRID_VERSION, "tree": migrated}))
                    if not m_err:
                        return json.dumps({"v": GRID_VERSION, "tree": m_tree}, ensure_ascii=False, separators=(",",":")), None
                    # Unfixable: REJECT, keep the stored layout (RULE 13) — never
                    # silently substitute default (that discards the user's grid).
                    log.warning(f"Migration still failed after window mismatch: {m_err}, rejecting")
                    return None, m_err or err
            except Exception as e:
                log.warning(f"Failed to migrate grid after mismatch {err}: {e}, rejecting")
                return None, err
        return None, err
    return json.dumps({"v": GRID_VERSION, "tree": tree}, ensure_ascii=False, separators=(",",":")), None

def _rename_legacy_windows(node):
    """Rewrite renamed window ids in a stored tree (identity elsewhere)."""
    if not isinstance(node, dict):
        return node
    t = node.get("t", node.get("type"))
    if t == "leaf":
        new_id = LEGACY_WINDOW_IDS.get(node.get("id"))
        return {**node, "id": new_id} if new_id else node
    if t == "split" and isinstance(node.get("children"), list):
        return {**node, "children": [_rename_legacy_windows(k) for k in node["children"]]}
    return node


def migrate_grid_tree(tree: dict) -> dict:
    tree = _rename_legacy_windows(tree)
    present = {i for i in leaf_ids(tree) if i}
    missing = [i for i in sorted(WINDOW_IDS) if i not in present]
    if not missing:
        return tree
    if len(missing) == 1:
        extra = {"t":"leaf","id":missing[0]}
    else:
        share = round(100/len(missing),4)
        sizes = [share]*len(missing)
        sizes[0] = round(100 - share*(len(missing)-1),4)
        extra = {"t":"split","dir":"row","children":[{"t":"leaf","id":i} for i in missing],"sizes":sizes}
    room = min(40, max(MIN_GRID_SIZE, len(missing)*9))
    return {"t":"split","dir":"col","children":[tree, extra],"sizes":[100-room, room]}

def node_type(node):
    return node.get("t", node.get("type")) if isinstance(node, dict) else None
