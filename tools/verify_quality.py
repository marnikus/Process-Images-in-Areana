#!/usr/bin/env python3
"""
RULE 16 gate — size and complexity limits for Arena Image Processor.

Two check modes:
  full tree (default): every app file must respect the hard limits.
      --allow-legacy demotes breaches in baseline-listed files to warnings.
  --changed (the push gate): only files changed vs origin/main (plus the
      uncommitted worktree) are checked, and for files that exist in the
      baseline v2 a RATCHET applies:
        * symbol new-to-baseline breaching a hard limit        -> FAIL
        * symbol in baseline that regressed on any metric      -> FAIL
        * symbol in baseline within baseline but over hard     -> WARN (legacy)
        * file coverage below its baseline value               -> FAIL

Baseline format v2 (tools/quality_baseline.json):
  {"version": 2,
   "files": {"app/x.py": {"functions": {name: {loc, params, cc, cognitive, nesting}},
                          "classes": {name: {loc, methods}},
                          "coverage": 43.2}},
   "js": {"app/ui/web/js/y.js": {"functions": {name: {loc, params, nesting, cc}},
                                 "file_lines": 210}}}
Regenerate with:  python tools/baseline_update.py

Usage:
    python tools/verify_quality.py               # full tree
    python tools/verify_quality.py --changed --allow-legacy   # push gate
    python tools/verify_quality.py --json        # machine-readable
    python tools/verify_quality.py --root DIR    # test harnesses
    python tools/verify_quality.py --changed-files a.py b.py  # explicit change set

Thresholds (from docs/current/AGENT_RULES.md RULE 16):
    Function LOC: prefer ≤20, fail >30
    Class LOC: prefer ≤120, fail >150
    Params: prefer ≤3, fail >4
    Methods per class: prefer ≤10, fail >15
    CC: prefer ≤7, fail >10
    Cognitive: prefer ≤10, fail >15
    Nesting: prefer ≤3, fail >4
    Coverage: line ≥80%, branch ≥75%, per-file never below baseline

Override format (strict):
    # quality-override: metric=value reason=<≥20 chars>
    metric ∈ loc, class-loc, params, methods, cc, cognitive, nesting

Anti-gaming checks:
    - no foo_part1/part2 split to game LOC
    - no **kwargs dodge for params
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

# Fail thresholds (from AGENT_RULES.md)
LIMITS = {
    "func_loc": 30,
    "class_loc": 150,
    "params": 4,
    "methods": 15,
    "cc": 10,
    "cognitive": 15,
    "nesting": 4,
}
PREFER = {
    "func_loc": 20,
    "class_loc": 120,
    "params": 3,
    "methods": 10,
    "cc": 7,
    "cognitive": 10,
    "nesting": 3,
}

# Files out of scope for size/CC (tests, tools, docs, generated)
OUT_OF_SCOPE_PATTERNS = [
    r"^tests/",
    r"^tools/",
    r"^docs/",
    r"/__pycache__/",
    r"\.pyc$",
    r"^config/",
    r"^research/",
    r"^mutants/",
]

OVERRIDE_RE = re.compile(
    r"quality-override:\s*"
    r"(?P<metric>loc|class-loc|params|methods|cc|cognitive|nesting|coverage|vulture|dup)"
    r"\s*=\s*(?P<value>\S+)\s+reason=(?P<reason>.+)",
    re.IGNORECASE,
)

METRIC_TO_OVERRIDE = {
    "loc": "loc", "params": "params", "cc": "cc", "cognitive": "cognitive",
    "nesting": "nesting", "class-loc": "class-loc", "methods": "methods",
}


def is_out_of_scope(root: Path, path: Path) -> bool:
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    return any(re.search(pat, rel) for pat in OUT_OF_SCOPE_PATTERNS)


def _git(root: Path, *args: str) -> Optional[str]:
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def changed_py_files(root: Path, explicit: Optional[List[str]] = None) -> Tuple[List[Path], str]:
    """Changed app/*.py files. Returns (files, note).

    Changed = committed diff vs merge-base(origin/main, HEAD) + staged +
    unstaged + untracked (worktree-safe: uncommitted work is gated too).
    """
    if explicit:
        files = []
        for rel in explicit:
            p = root / rel
            if p.suffix == ".py" and p.exists() and not is_out_of_scope(root, p):
                files.append(p)
        return sorted(files), "explicit"

    names: set[str] = set()
    base = _git(root, "merge-base", "origin/main", "HEAD")
    note = ""
    if base:
        out = _git(root, "diff", "--name-only", f"{base.strip()}...HEAD") or ""
        names.update(out.split())
    else:
        # no merge base (e.g. re-rooted sandbox history): gate the whole tree
        note = "no merge base with origin/main — checking whole tree"
        return find_py_files(root), note
    for args in (("diff", "--name-only", "HEAD"),
                 ("diff", "--cached", "--name-only"),
                 ("ls-files", "--others", "--exclude-standard")):
        out = _git(root, *args) or ""
        names.update(out.split())

    files = []
    for rel in sorted(names):
        p = root / rel
        if p.suffix == ".py" and p.exists() and not is_out_of_scope(root, p):
            files.append(p)
    return files, note


def find_py_files(root: Path) -> List[Path]:
    app_dir = root / "app"
    return sorted(p for p in app_dir.rglob("*.py") if not is_out_of_scope(root, p))


def get_override_comment(node: ast.AST, source_lines: List[str]) -> Dict[str, Tuple[str, str]]:
    """Parse quality-override comments for a node. Returns metric -> (value, reason)."""
    overrides: Dict[str, Tuple[str, str]] = {}
    try:
        lineno = getattr(node, "lineno", 1)
        for i in range(max(0, lineno - 3), min(len(source_lines), lineno + 1)):
            m = OVERRIDE_RE.search(source_lines[i])
            if m:
                overrides[m.group("metric").lower()] = (m.group("value"), m.group("reason").strip())
    except Exception:
        pass
    return overrides


def count_params(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = func_node.args
    return len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)


def method_param_count(node: ast.FunctionDef | ast.AsyncFunctionDef, in_class: bool) -> int:
    n = count_params(node)
    if in_class:
        try:
            first = (node.args.posonlyargs or node.args.args)
            if first and first[0].arg in ("self", "cls"):
                n = max(0, n - 1)
        except Exception:
            pass
    return n


def get_nesting_depth(node: ast.AST, current_depth: int = 0, max_depth: int = 0) -> int:
    """Max nesting depth of branching constructs (If/For/While/With/Try)."""
    new_depth = current_depth
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.Try)):
        new_depth = current_depth + 1
        max_depth = max(max_depth, new_depth)
    for child in ast.iter_child_nodes(node):
        max_depth = get_nesting_depth(child, new_depth, max_depth)
    return max_depth


def compute_cc_simple(node: ast.AST) -> int:
    """Simple cyclomatic complexity approximation: base 1 + branching."""
    cc = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With)):
            cc += 1
        elif isinstance(n, ast.BoolOp) and isinstance(n.op, (ast.And, ast.Or)):
            cc += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            cc += len(n.ifs)
        elif isinstance(n, ast.IfExp):
            cc += 1
        elif isinstance(n, ast.Assert):
            cc += 1
    return cc


def _try_cognitive_map(file_path: Path) -> Dict[str, int]:
    try:
        from cognitive_complexity.api import get_cognitive_complexity  # type: ignore
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        result: Dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    result[node.name] = get_cognitive_complexity(node)
                except Exception:
                    pass
        return result
    except Exception:
        return {}


def node_loc(node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None) or node.lineno
    return end - node.lineno + 1


def analyze_file(file_path: Path) -> Dict[str, Any]:
    """Per-symbol metrics table for one Python file.

    functions: {qualified_name: {loc, params, cc, cognitive, nesting}}
      module-level: "name"; methods: "ClassName.name"
    classes: {name: {loc, methods}}
    """
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    cog_map = _try_cognitive_map(file_path)

    functions: Dict[str, Dict[str, int]] = {}
    classes: Dict[str, Dict[str, int]] = {}
    seen: set[str] = set()

    def unique_name(base: str) -> str:
        name, i = base, 2
        while name in seen:
            name = f"{base}#{i}"
            i += 1
        seen.add(name)
        return name

    def walk(node: ast.AST, class_stack: List[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = ".".join(class_stack + [node.name]) if class_stack else node.name
            name = unique_name(qual)
            in_class = bool(class_stack)
            functions[name] = {
                "loc": node_loc(node),
                "params": method_param_count(node, in_class),
                "cc": compute_cc_simple(node),
                "cognitive": cog_map.get(node.name, 0),
                "nesting": get_nesting_depth(node),
            }
        if isinstance(node, ast.ClassDef):
            methods = [n for n in node.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes[node.name] = {"loc": node_loc(node), "methods": len(methods)}
            for child in ast.iter_child_nodes(node):
                walk(child, class_stack + [node.name])
            return
        for child in ast.iter_child_nodes(node):
            walk(child, class_stack)

    walk(tree, [])
    return {"functions": functions, "classes": classes}


def syntax_error(file_path: Path, err: Exception) -> Dict[str, Any]:
    return {"file": str(file_path), "error": f"syntax error: {err}", "fail": True}


def check_hard_limits(rel: str, table: Dict[str, Any], source: str) -> List[Dict]:
    """Original hard-limit checks on one file (full-tree mode + new symbols)."""
    breaches: List[Dict] = []
    source_lines = source.splitlines()

    def add(btype: str, name: str, lineno: int, metric: str, value: int,
            limit: int, prefer: int, anti_gaming: bool = False, message: str = "") -> None:
        breaches.append({
            "file": rel, "type": btype, "name": name, "lineno": lineno,
            "metric": "anti-gaming" if anti_gaming else metric,
            "value": value, "limit": limit, "prefer": prefer,
            "fail": True, "message": message,
        })

    tree = ast.parse(source)
    _walk_for_limits(tree, rel, source_lines, breaches, add)
    return breaches


def _walk_for_limits(tree: ast.AST, rel: str, source_lines: List[str],
                     breaches: List[Dict], add) -> None:
    def walk(node: ast.AST, class_stack: List[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            in_class = bool(class_stack)
            name = ".".join(class_stack + [node.name]) if class_stack else node.name
            overrides = get_override_comment(node, source_lines)
            if re.search(r"_part\d+$", node.name):
                add("function", name, node.lineno, "anti-gaming", 0, 0, 0, True,
                    f"Function {name} looks like gaming split foo_part1/part2 (RULE 16 anti-gaming)")

            def fail(metric: str, value: int, limit: int, prefer: int, message: str) -> None:
                om = METRIC_TO_OVERRIDE.get(metric)
                if om and om in overrides:
                    reason = overrides[om][1]
                    if len(reason) < 20:
                        breaches.append({
                            "file": rel, "type": "function", "name": name,
                            "lineno": node.lineno, "metric": f"{om}-override-reason",
                            "fail": True,
                            "message": f"Override reason too short (<20 chars) for {name}: {reason}",
                        })
                    return
                add("function", name, node.lineno, metric, value, limit, prefer, False, message)

            if node_loc(node) > LIMITS["func_loc"]:
                fail("loc", node_loc(node), LIMITS["func_loc"], PREFER["func_loc"],
                     f"Function {name} LOC {node_loc(node)} > {LIMITS['func_loc']} "
                     f"(prefer ≤{PREFER['func_loc']}) at {rel}:{node.lineno}")
            params = method_param_count(node, in_class)
            if params > LIMITS["params"]:
                if node.args.kwarg is not None and params <= 1:
                    add("function", name, node.lineno, "anti-gaming", params, 4, 3, True,
                        f"Function {name} uses **kwargs to dodge params count (RULE 16 anti-gaming)")
                fail("params", params, LIMITS["params"], PREFER["params"],
                     f"Function {name} params {params} > {LIMITS['params']} (prefer ≤{PREFER['params']})")
            cc = compute_cc_simple(node)
            if cc > LIMITS["cc"]:
                fail("cc", cc, LIMITS["cc"], PREFER["cc"],
                     f"Function {name} CC {cc} > {LIMITS['cc']} (prefer ≤{PREFER['cc']})")
            cog = node_cognitive(node)
            if cog > LIMITS["cognitive"]:
                fail("cognitive", cog, LIMITS["cognitive"], PREFER["cognitive"],
                     f"Function {name} cognitive {cog} > {LIMITS['cognitive']}")
            nest = get_nesting_depth(node)
            if nest > LIMITS["nesting"]:
                fail("nesting", nest, LIMITS["nesting"], PREFER["nesting"],
                     f"Function {name} nesting {nest} > {LIMITS['nesting']}")
            for child in ast.iter_child_nodes(node):
                walk(child, class_stack)
            return
        if isinstance(node, ast.ClassDef):
            overrides = get_override_comment(node, source_lines)
            loc = node_loc(node)
            if loc > LIMITS["class_loc"] and "class-loc" not in overrides and "loc" not in overrides:
                add("class", node.name, node.lineno, "class-loc", loc,
                    LIMITS["class_loc"], PREFER["class_loc"], False,
                    f"Class {node.name} LOC {loc} > {LIMITS['class_loc']} (prefer ≤{PREFER['class_loc']})")
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if len(methods) > LIMITS["methods"] and "methods" not in overrides:
                add("class", node.name, node.lineno, "methods", len(methods),
                    LIMITS["methods"], PREFER["methods"], False,
                    f"Class {node.name} methods {len(methods)} > {LIMITS['methods']}")
            for child in ast.iter_child_nodes(node):
                walk(child, class_stack + [node.name])
            return
        for child in ast.iter_child_nodes(node):
            walk(child, class_stack)

    walk(tree, [])


def node_cognitive(node: ast.AST) -> int:
    try:
        from cognitive_complexity.api import get_cognitive_complexity  # type: ignore
        return get_cognitive_complexity(node)
    except Exception:
        return 0


RATCHET_FN_KEYS = {"loc": "loc", "params": "params", "cc": "cc", "cognitive": "cognitive",
                   "nesting": "nesting"}
RATCHET_CLS_KEYS = {"class-loc": "loc", "methods": "methods"}
RATCHET_METRIC_KEY = {**RATCHET_FN_KEYS, **RATCHET_CLS_KEYS}


def apply_ratchet(rel: str, breaches: List[Dict], table: Dict[str, Any],
                  base_entry: Dict[str, Any], allow_legacy: bool) -> List[Dict]:
    """Baseline v2 ratchet for a changed file that exists in the baseline.

    * every symbol regressing on any metric (above its baseline value) -> FAIL,
      even when still below the hard limit
    * new-to-baseline symbol breaching a hard limit                    -> FAIL
    * pre-existing breach within the baseline                          -> WARN
      with --allow-legacy (grandfathered), FAIL in strict mode
    Anti-gaming breaches never demote.
    """
    base_fns = base_entry.get("functions") or {}
    base_cls = base_entry.get("classes") or {}
    cur_fns = table.get("functions") or {}
    cur_cls = table.get("classes") or {}

    regressed: set[Tuple[str, str, str]] = set()  # (btype, name, metric)
    for btype, base_map, cur_map, keys in (
            ("function", base_fns, cur_fns, RATCHET_FN_KEYS),
            ("class", base_cls, cur_cls, RATCHET_CLS_KEYS)):
        for name, cur in cur_map.items():
            base_sym = base_map.get(name)
            if not base_sym:
                continue
            for metric, key in keys.items():
                if cur.get(key, 0) > base_sym.get(key, 0):
                    regressed.add((btype, name, metric))

    reported = {(b.get("name"), b.get("metric")) for b in breaches}
    regressed_pairs = {(name, metric) for _, name, metric in regressed}
    for b in breaches:
        if b.get("metric") == "anti-gaming":
            continue
        if (b.get("name"), b.get("metric")) in regressed_pairs:
            sym = base_fns.get(b.get("name", "")) or base_cls.get(b.get("name", "")) or {}
            key = RATCHET_METRIC_KEY.get(b.get("metric", ""), b.get("metric"))
            b["message"] = (f"{b.get('message')} — regressed vs baseline "
                            f"{sym.get(key)} -> {b.get('value')} (ratchet: no growth)")
            continue
        sym = base_fns.get(b.get("name", "")) or base_cls.get(b.get("name", ""))
        if sym is None:
            continue  # new symbol: hard-limit breach stays a fail
        key = RATCHET_METRIC_KEY.get(b.get("metric", ""), b.get("metric"))
        base_v = sym.get(key)
        if base_v is None or b.get("value", 0) > base_v:
            continue  # regression: stays a fail
        b["fail"] = not allow_legacy
        b["message"] = (f"[LEGACY] {b.get('message')} (within baseline {base_v}; "
                        f"pre-existing, not a regression)")

    # regressions that never breached a hard limit are not in `breaches` yet
    for btype, base_map, cur_map, keys in (
            ("function", base_fns, cur_fns, RATCHET_FN_KEYS),
            ("class", base_cls, cur_cls, RATCHET_CLS_KEYS)):
        for rb, name, metric in sorted(regressed):
            if rb != btype or (name, metric) in reported:
                continue
            key = keys[metric]
            base_v = base_map[name].get(key, 0)
            cur_v = cur_map[name].get(key, 0)
            breaches.append({
                "file": rel, "type": btype, "name": name, "metric": metric,
                "value": cur_v, "limit": base_v, "fail": True,
                "message": f"{btype.capitalize()} {name} {metric} regressed "
                           f"{base_v} -> {cur_v} (baseline ratchet: no growth)",
            })
    return breaches


def load_baseline(root: Path, path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def baseline_file_entry(baseline: Dict[str, Any], rel: str) -> Optional[Dict[str, Any]]:
    if baseline.get("version") == 2:
        return (baseline.get("files") or {}).get(rel)
    # v1 compat: flat {rel: {max_func_loc, max_class_loc, func_count}}
    entry = baseline.get(rel)
    return entry


def check_coverage(root: Path, changed_files: Optional[List[Path]],
                   baseline: Dict[str, Any]) -> List[Dict]:
    breaches: List[Dict] = []
    cov_path = root / "coverage.json"
    data: Dict[str, Any] = {}
    if cov_path.exists():
        try:
            data = json.loads(cov_path.read_text(encoding="utf-8"))
        except Exception as e:
            breaches.append({"file": "coverage.json", "type": "coverage", "fail": False,
                             "message": f"Failed to parse coverage.json: {e}"})
            return breaches
    else:
        breaches.append({
            "file": "coverage.json", "type": "coverage", "metric": "missing", "fail": False,
            "message": "coverage.json not found — run: "
                       "python -m coverage run --branch --source=app -m pytest tests -q "
                       "&& python -m coverage json -o coverage.json",
        })
        return breaches

    totals = data.get("totals", {})
    line_pct = totals.get("percent_covered", 0)
    covered_branches = totals.get("covered_branches", 0)
    num_branches = totals.get("num_branches", 0)
    branch_pct = (covered_branches / num_branches * 100) if num_branches else 0
    if line_pct < 80:
        breaches.append({"file": "coverage.json", "type": "coverage", "metric": "line",
                         "value": line_pct, "limit": 80, "fail": True,
                         "message": f"Line coverage {line_pct:.1f}% < 80%"})
    if branch_pct < 75 and num_branches > 0:
        breaches.append({"file": "coverage.json", "type": "coverage", "metric": "branch",
                         "value": branch_pct, "limit": 75, "fail": True,
                         "message": f"Branch coverage {branch_pct:.1f}% < 75%"})

    # per-file ratchet (baseline v2) for changed files
    if baseline.get("version") == 2 and changed_files:
        files = data.get("files") or {}
        for p in changed_files:
            try:
                rel = str(p.relative_to(root))
            except ValueError:
                continue
            base_cov = (baseline.get("files") or {}).get(rel, {}).get("coverage")
            if base_cov is None:
                continue
            fdata = files.get(rel)
            if not fdata:
                continue
            cur_cov = fdata.get("summary", {}).get("percent_covered", 0)
            # 0.05pp epsilon: covers double-rounding noise between coverage.json
            # (full precision) and the baseline (stored at 2dp); real drops >=0.1pp fail
            if cur_cov + 0.05 < base_cov:
                breaches.append({
                    "file": rel, "type": "coverage", "metric": "per-file",
                    "value": round(cur_cov, 2), "limit": base_cov, "fail": True,
                    "message": f"Per-file line coverage {cur_cov:.1f}% below baseline {base_cov:.1f}% (ratchet)",
                })
    return breaches


def main() -> None:
    parser = argparse.ArgumentParser(description="RULE 16 quality gate for Arena")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument("--changed", action="store_true",
                        help="only check files changed vs origin/main (plus worktree)")
    parser.add_argument("--allow-legacy", action="store_true",
                        help="baseline v2: grandfather pre-existing breaches as warnings")
    parser.add_argument("--root", type=str, default=None, help="repo root (test harnesses)")
    parser.add_argument("--changed-files", nargs="*", default=None,
                        help="explicit changed files (overrides git detection)")
    parser.add_argument("--baseline", type=str, default="tools/quality_baseline.json",
                        help="baseline file for legacy/ratchet")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else DEFAULT_ROOT
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path
    baseline_data = load_baseline(root, baseline_path)
    changed_mode = bool(args.changed or args.changed_files)

    if changed_mode:
        files, note = changed_py_files(root, args.changed_files)
    else:
        files, note = find_py_files(root), ""

    all_breaches: List[Dict] = []
    for f in files:
        try:
            rel = str(f.relative_to(root))
        except ValueError:
            rel = str(f)
        try:
            source = f.read_text(encoding="utf-8")
            ast.parse(source)
        except Exception as e:
            all_breaches.append(syntax_error(f, e))
            continue
        table = analyze_file(f)
        hard = check_hard_limits(rel, table, source)
        base_entry = baseline_file_entry(baseline_data, rel)
        if changed_mode and baseline_data.get("version") == 2 and base_entry is not None:
            # push-gate ratchet: regressions/new-symbol breaches fail, pre-existing
            # within-baseline breaches grandfathered (warn with --allow-legacy)
            hard = apply_ratchet(rel, hard, table, base_entry, args.allow_legacy)
        elif args.allow_legacy and base_entry is not None:
            # full-tree legacy mode (v1 compat): demote all in-baseline breaches
            for b in hard:
                if b.get("metric") != "anti-gaming":
                    b["fail"] = False
                    b["message"] = f"[LEGACY] {b['message']}"
        all_breaches.extend(hard)

    all_breaches.extend(check_coverage(root, files if changed_mode else None, baseline_data))

    fails = [b for b in all_breaches if b.get("fail")]
    warns = [b for b in all_breaches if not b.get("fail")]

    if args.json:
        print(json.dumps({"breaches": all_breaches, "fails": fails, "warns": warns,
                          "files_checked": len(files), "note": note},
                         indent=2, ensure_ascii=False))
        sys.exit(1 if fails else 0)

    print(f"Checked {len(files)} files" + (f" ({note})" if note else ""))
    print(f"Found {len(fails)} fail(s), {len(warns)} warn(s)")
    print("")
    if fails:
        print("=== FAILS (must fix before push) ===")
        for b in fails:
            print(f"{b.get('file')}:{b.get('lineno', '')} [{b.get('metric')}] {b.get('message')}")
        print("")
    if warns:
        print("=== WARNS (should fix, not blocking) ===")
        for b in warns:
            print(f"{b.get('file')} [{b.get('metric', '')}] {b.get('message')}")
        print("")
    if not fails:
        print("✅ Quality gate PASSED — no fails")
        print("")
        print("Preferences (not failing, but aim):")
        print(f"  Function LOC prefer ≤{PREFER['func_loc']}, fail >{LIMITS['func_loc']}")
        print(f"  Class LOC prefer ≤{PREFER['class_loc']}, fail >{LIMITS['class_loc']}")
        print(f"  Params prefer ≤{PREFER['params']}, fail >{LIMITS['params']}")
        print(f"  Methods per class prefer ≤{PREFER['methods']}, fail >{LIMITS['methods']}")
        print(f"  CC prefer ≤{PREFER['cc']}, fail >{LIMITS['cc']}")
        print(f"  Cognitive prefer ≤{PREFER['cognitive']}, fail >{LIMITS['cognitive']}")
        print(f"  Nesting prefer ≤{PREFER['nesting']}, fail >{LIMITS['nesting']}")
        print("  Coverage line ≥80%, branch ≥75%, per-file never below baseline")
    else:
        print("❌ Quality gate FAILED — fix fails before push (RULE 16)")
        print("")
        print("Remediation order (RULE 19): nesting → CC → cognitive → size")
        print("  1. Nesting >4 → extract guard, early return, flatten")
        print("  2. CC >10 → split decision, not just code (no foo_part1)")
        print("  3. Cognitive >15 → name predicates, simplify boolean")
        print("  4. LOC >30 → extract helper with real responsibility name")
        print("  Regressed vs baseline → restore the previous shape; ratchets never grow.")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
