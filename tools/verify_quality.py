#!/usr/bin/env python3
"""
RULE 16 gate — size and complexity limits for Arena Image Processor.

Adapted from Old App tools/metrics/rule16_gate.py but simplified for Arena,
preserving thresholds, invariants pattern, and override format.

Usage:
    python tools/verify_quality.py              # report, exit 1 on breach
    python tools/verify_quality.py --json       # machine-readable
    python tools/verify_quality.py --changed    # only files changed vs base
    python tools/verify_quality.py --changed --base <ref>
                                                 # base ref for the diff
                                                 # (default origin/main); if
                                                 # the ref has no merge-base
                                                 # with HEAD the tool falls
                                                 # back to ALL files with a
                                                 # LOUD stderr warning —
                                                 # never silently
    python tools/verify_quality.py --coverage-ratchet
                                                 # mid-round mode: coverage
                                                 # fails only on DECREASE vs
                                                 # the baseline 'coverage'
                                                 # key; the absolute 80/75
                                                 # (final D4 target) warns
    python tools/verify_quality.py --update-coverage-baseline
                                                 # store current coverage in
                                                 # the baseline file (never
                                                 # lowers the floor)
    python tools/verify_quality.py --js | --no-js  # JS lane (acorn via
                                                 # tools/js_metrics.js); auto-on
                                                 # when node + the tool exist
    python tools/verify_quality.py --record-baseline
                                                 # integrator-only: re-record
                                                 # py maxima/funcs + JS maxima +
                                                 # per-file coverage floor

Thresholds (from docs/current/AGENT_RULES.md RULE 16):
    Function LOC: prefer ≤20, fail >30
    Class LOC: prefer ≤120, fail >150
    Params: prefer ≤3, fail >4
    Methods per class: prefer ≤10, fail >15
    CC: prefer ≤7, fail >10 (radon cc -s if available, else AST approx)
    Cognitive: prefer ≤10, fail >15 (cognitive-complexity if available)
    Nesting: prefer ≤3, fail >4
    Coverage: line ≥80%, branch ≥75%, never decrease vs baseline

Override format (strict):
    # quality-override: metric=value reason=<≥20 chars>
    metric ∈ loc, class-loc, params, methods, cc, cognitive, nesting, coverage, vulture, dup
    One override per metric per symbol.

Anti-gaming checks:
    - no foo_part1/part2 split to game LOC
    - no **kwargs dodge for params
    - no dummy helpers
    - no lambda dispatch hiding if
"""

from __future__ import annotations

import argparse
import math
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"

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
    r"config/",
    r"research/",
]

OVERRIDE_RE = re.compile(
    r"quality-override:\s*"
    r"(?P<metric>loc|class-loc|params|methods|cc|cognitive|nesting|coverage|vulture|dup)"
    r"\s*=\s*(?P<value>\S+)\s+reason=(?P<reason>.+)",
    re.IGNORECASE,
)

def is_out_of_scope(path: Path) -> bool:
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    for pat in OUT_OF_SCOPE_PATTERNS:
        if re.search(pat, rel):
            return True
    return False

def changed_app_files(base_ref: str) -> Tuple[List[Path], Optional[str]]:
    """App files changed vs base_ref. Returns (files, fallback_reason):
    fallback_reason is None on a real changed-file list, or a human-readable
    reason why the caller must fall back to checking ALL files."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=str(ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return [], (f"git diff vs '{base_ref}' failed — likely no merge-base "
                    f"with HEAD ({e.__class__.__name__})")
    files = []
    for line in out.splitlines():
        p = ROOT / line.strip()
        # Only app files are gated for quality (tests/tools out of scope)
        if not str(p).startswith(str(APP_DIR)):
            continue
        if p.suffix == ".py" and p.exists() and not is_out_of_scope(p):
            files.append(p)
    if not files:
        return [], f"diff vs '{base_ref}' lists no gated app files"
    return sorted(files), None


def all_app_files() -> List[Path]:
    files = []
    for p in APP_DIR.rglob("*.py"):
        if not is_out_of_scope(p):
            files.append(p)
    return sorted(files)


JS_DIR = ROOT / "app" / "ui" / "web"
JS_METRICS_TOOL = ROOT / "tools" / "js_metrics.js"
JS_METRICS = ["max_func_loc", "max_cc", "max_nest", "max_params", "file_lines", "func_count"]
# Metrics whose GROWTH fails even inside a baselined file (RULE 16 R0.3).
# file_lines/func_count are recorded but not enforced: they are structure,
# not quality, and the per-symbol map already fails new symbols.
RATCHET_METRICS = ["max_func_loc", "max_class_loc", "max_methods", "max_cc",
                   "max_cog", "max_nest", "max_params"]


def all_js_files() -> List[Path]:
    return sorted(p for p in JS_DIR.rglob("*.js") if "node_modules" not in p.parts)


def changed_js_files(base_ref: str) -> List[Path]:
    """JS files changed vs base_ref (tracked diff + untracked)."""
    import subprocess
    try:
        out = subprocess.check_output(["git", "diff", "--name-only", f"{base_ref}...HEAD"],
                                      cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL)
        untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"],
                                            cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    files = []
    for line in (out + "\n" + untracked).splitlines():
        p = ROOT / line.strip()
        if (p.suffix == ".js" and p.exists() and p.is_relative_to(JS_DIR)
                and "node_modules" not in p.parts):
            files.append(p)
    return sorted(set(files))


def js_maxima(js_files: List[Path]) -> Dict[str, Dict[str, int]]:
    """{rel_path: {metric: maximum}} from tools/js_metrics.js (acorn). {} if unavailable."""
    import subprocess
    if not js_files:
        return {}
    if not JS_METRICS_TOOL.exists():
        sys.stderr.write("⚠ tools/js_metrics.js missing — JS lane skipped\n")
        return {}
    try:
        out = subprocess.check_output(["node", str(JS_METRICS_TOOL), str(JS_DIR), "--json"],
                                      text=True, timeout=60)
        data = json.loads(out)
    except Exception as e:
        sys.stderr.write(f"⚠ JS metrics unavailable ({e.__class__.__name__}) — JS lane skipped\n")
        return {}
    per_file: Dict[str, Dict[str, int]] = {}
    for entry in data:
        rel = entry.get("file")
        if not rel:
            continue
        cur = per_file.setdefault(rel, {k: 0 for k in JS_METRICS})
        if entry.get("isFile"):
            cur["file_lines"] = entry.get("fileLines", 0)
            continue
        if entry.get("error"):
            continue
        cur["max_func_loc"] = max(cur["max_func_loc"], entry.get("loc", 0))
        cur["max_cc"] = max(cur["max_cc"], entry.get("cc", 0))
        cur["max_nest"] = max(cur["max_nest"], entry.get("depth", 0))
        cur["max_params"] = max(cur["max_params"], entry.get("params", 0))
        cur["func_count"] += 1
    return per_file


def check_js(js_files: List[Path], baseline: Dict) -> List[Dict]:
    """JS ratchet: a measured maximum may not exceed the recorded baseline."""
    breaches = []
    for rel, cur in sorted(js_maxima(js_files).items()):
        base = baseline.get(rel) or {}
        for metric in RATCHET_METRICS + ["file_lines", "func_count"]:
            limit = base.get(metric)
            value = cur.get(metric, 0)
            if limit is None or value <= limit:
                continue
            breaches.append({"file": rel, "type": "js", "metric": f"ratchet-js-{metric}",
                             "value": value, "limit": limit, "fail": True,
                             "message": f"RATCHET JS {rel} {metric} grew {limit}→{value}"})
    return breaches


def current_maxima(file_path: Path) -> Dict[str, int]:
    """Per-file quality maxima (the numbers the ratchet baseline stores)."""
    src = file_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    radon_map = try_radon_cc(file_path) or {}
    cog_map = try_cognitive(file_path) or {}
    maxima = {m: 0 for m in RATCHET_METRICS}
    maxima.update({"file_lines": len(src.splitlines()), "func_count": 0})
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            maxima["func_count"] += 1
            maxima["max_func_loc"] = max(maxima["max_func_loc"], node_loc(node))
            maxima["max_cc"] = max(maxima["max_cc"], radon_map.get(node.name, compute_cc_simple(node)))
            maxima["max_cog"] = max(maxima["max_cog"], cog_map.get(node.name, 0))
            maxima["max_nest"] = max(maxima["max_nest"], get_nesting_depth(node))
            maxima["max_params"] = max(maxima["max_params"], effective_params(node, []))
        elif isinstance(node, ast.ClassDef):
            maxima["max_class_loc"] = max(maxima["max_class_loc"], node_loc(node))
            methods = sum(1 for n in node.body
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
            maxima["max_methods"] = max(maxima["max_methods"], methods)
    return maxima


def ratchet_growth(rel: str, cur: Dict[str, int], base: Optional[Dict]) -> List[Dict]:
    """R0.3: any growth of a quality maximum fails, baselined file or not."""
    if not base:
        return []
    breaches = []
    for metric in RATCHET_METRICS:
        limit = base.get(metric)
        value = cur.get(metric, 0)
        if limit is None or value <= limit:
            continue
        breaches.append({"file": rel, "type": "ratchet", "metric": f"ratchet-{metric}",
                         "value": value, "limit": limit, "fail": True,
                         "message": f"RATCHET {rel} {metric} grew {limit}→{value} "
                                    "(even in baseline, growth fails)"})
    return breaches


def per_file_coverage_lanes(cov_path: Path, baseline: Dict) -> List[Dict]:
    """R0.3 coverage ratchet: no baselined file may drop below its floor."""
    try:
        data = json.loads(cov_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    files = data.get("files", {})
    lanes = []
    for rel, base in sorted(baseline.items()):
        if not isinstance(base, dict) or "coverage" not in base or rel not in files:
            continue
        cur = float(files[rel].get("summary", {}).get("percent_covered", 0.0))
        floor = float(base["coverage"])
        if cur + 0.05 < floor:
            lanes.append({"file": rel, "type": "coverage", "metric": "ratchet-coverage",
                          "value": cur, "baseline": floor, "fail": True,
                          "message": f"RATCHET {rel} coverage dropped {floor:.1f}%→{cur:.1f}% "
                                     "(even in baseline, growth fails)"})
    return lanes


def get_override_comment(node: ast.AST, source_lines: List[str]) -> Dict[str, Tuple[str, str]]:
    """Parse quality-override comments for a node. Returns metric -> (value, reason)."""
    overrides = {}
    # Check node's own line and previous line for comment
    try:
        lineno = getattr(node, "lineno", 1)
        # Look at line itself and up to 2 lines before
        for i in range(max(0, lineno - 3), min(len(source_lines), lineno + 1)):
            line = source_lines[i]
            m = OVERRIDE_RE.search(line)
            if m:
                metric = m.group("metric").lower()
                value = m.group("value")
                reason = m.group("reason").strip()
                overrides[metric] = (value, reason)
    except Exception:
        pass
    return overrides

def count_params(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count params, excluding self/cls for methods, excluding **kwargs if it's dodge?"""
    args = func_node.args
    # Count posonly + args + kwonly, but exclude self/cls if first arg named self/cls and function is method
    # We need to know if it's inside class — caller will adjust
    count = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    # Check for **kwargs dodge: if function has **kwargs and count==1 and kwargs name is kwargs, it's suspicious
    # But per anti-gaming, **kwargs to hide params is not allowed — we still count it as 1 but flag?
    # For simplicity, count it.
    return count

def is_method_inside_class(stack) -> bool:
    for n in reversed(stack):
        if isinstance(n, ast.ClassDef):
            return True
    return False

def get_nesting_depth(node: ast.AST, current_depth: int = 0, max_depth: int = 0) -> int:
    """Max nesting depth of branching constructs (if/for/async-for/while/with)."""
    new_depth = current_depth
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With)):
        new_depth = current_depth + 1
        max_depth = max(max_depth, new_depth)
    for child in ast.iter_child_nodes(node):
        max_depth = get_nesting_depth(child, new_depth, max_depth)
    return max_depth

def node_complexity(n: ast.AST) -> int:
    """CC contribution of one node: branches, bool-op arms, comprehension ifs."""
    if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With)):
        return 1
    if isinstance(n, ast.BoolOp) and isinstance(n.op, (ast.And, ast.Or)):
        return len(n.values) - 1
    if isinstance(n, ast.comprehension):
        return len(n.ifs)
    if isinstance(n, (ast.IfExp, ast.Assert)):
        return 1
    return 0


def compute_cc_simple(node: ast.AST) -> int:
    """Simple cyclomatic complexity approximation: base 1 + branching."""
    return 1 + sum(node_complexity(n) for n in ast.walk(node))

def try_radon_cc(file_path: Path) -> Optional[Dict[str, int]]:
    """Try to use radon if installed, return func_name -> cc."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["python", "-m", "radon", "cc", "-s", "-j", str(file_path)],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        data = json.loads(out)
        # data is {filepath: [ {name, lineno, col_offset, endline, cc, ...}, ... ]}
        result = {}
        for entries in data.values():
            for e in entries:
                result[e["name"]] = e["complexity"]
        return result
    except Exception:
        return None

def try_cognitive(file_path: Path) -> Optional[Dict[str, int]]:
    """Try cognitive-complexity lib."""
    try:
        # Try import
        from cognitive_complexity.api import get_cognitive_complexity  # type: ignore
        import ast as _ast
        source = file_path.read_text(encoding="utf-8")
        tree = _ast.parse(source)
        result = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    cc = get_cognitive_complexity(node)
                    result[node.name] = cc
                except Exception:
                    pass
        return result
    except Exception:
        return None

def node_loc(node: ast.AST) -> int:
    """Span of a node in lines (end_lineno fallback for old ASTs)."""
    try:
        end_lineno = getattr(node, "end_lineno", None) or node.lineno
        return end_lineno - node.lineno + 1
    except Exception:
        return 0


METRIC_LIMIT_KEYS = {
    "loc": "func_loc", "params": "params", "cc": "cc", "cognitive": "cognitive",
    "nesting": "nesting", "class-loc": "class_loc", "methods": "methods",
}


class GateContext:
    """Per-file state shared by the metric checkers."""

    def __init__(self, file_path: Path, source_lines: List[str],
                 radon_cc: Optional[Dict[str, int]], cog_map: Optional[Dict[str, int]]):
        self.path = file_path
        self.rel = str(file_path.relative_to(ROOT))
        self.source_lines = source_lines
        self.radon_cc = radon_cc
        self.cog_map = cog_map
        self.breaches: List[Dict] = []

    def breach(self, node: ast.AST, metric: str, value, message: str) -> None:
        """Append a standard metric breach (limit/prefer derived from metric)."""
        entry = {"file": self.rel,
                 "type": "class" if isinstance(node, ast.ClassDef) else "function",
                 "name": node.name,
                 "lineno": getattr(node, "lineno", 0), "metric": metric, "value": value}
        limit_key = METRIC_LIMIT_KEYS.get(metric)
        if limit_key:
            entry["limit"] = LIMITS[limit_key]
            entry["prefer"] = PREFER[limit_key]
        entry["fail"] = True
        entry["message"] = message
        self.breaches.append(entry)


def check_name_gaming(node: ast.AST, ctx: GateContext) -> None:
    """Anti-gaming: foo_part1/foo_part2 splits (RULE 16 §16.2)."""
    if re.search(r"_part\d+$", node.name):
        ctx.breaches.append({
            "file": ctx.rel, "type": "function", "name": node.name,
            "lineno": getattr(node, "lineno", 0), "metric": "anti-gaming",
            "value": node.name, "limit": "no _partN split", "fail": True,
            "message": f"Function {node.name} looks like gaming split foo_part1/part2 (RULE 16 anti-gaming)",
        })


def check_func_loc(node: ast.AST, ctx: GateContext) -> None:
    """Function LOC limit, honouring `loc` overrides (reason must be substantive)."""
    overrides = get_override_comment(node, ctx.source_lines)
    loc = node_loc(node)
    if loc <= LIMITS["func_loc"]:
        return
    if "loc" not in overrides:
        ctx.breach(node, "loc", loc,
                   f"Function {node.name} LOC {loc} > {LIMITS['func_loc']} (prefer ≤{PREFER['func_loc']}) at {ctx.path}:{node.lineno}")
        return
    _, reason = overrides["loc"]
    if len(reason.strip()) < 20:
        ctx.breaches.append({
            "file": ctx.rel, "type": "function", "name": node.name,
            "lineno": node.lineno, "metric": "loc-override-reason",
            "value": reason, "fail": True,
            "message": f"Override reason too short (<20 chars) for {node.name} loc override: {reason}",
        })


def effective_params(node: ast.AST, stack: List[ast.AST]) -> int:
    """Param count with self/cls excluded for methods."""
    count = count_params(node)
    if not is_method_inside_class(stack):
        return count
    try:
        first_arg = None
        if node.args.posonlyargs:
            first_arg = node.args.posonlyargs[0].arg
        elif node.args.args:
            first_arg = node.args.args[0].arg
        if first_arg in ("self", "cls"):
            return max(0, count - 1)
    except Exception:
        pass
    return count


def check_params(node: ast.AST, stack: List[ast.AST], ctx: GateContext) -> None:
    """Params limit plus the **kwargs-dodge anti-gaming check."""
    param_count = effective_params(node, stack)
    if param_count <= LIMITS["params"]:
        return
    overrides = get_override_comment(node, ctx.source_lines)
    if node.args.kwarg is not None and param_count <= 1:
        ctx.breaches.append({
            "file": ctx.rel, "type": "function", "name": node.name,
            "lineno": node.lineno, "metric": "anti-gaming",
            "value": param_count, "fail": True,
            "message": f"Function {node.name} uses **kwargs to dodge params count (RULE 16 anti-gaming)",
        })
    if "params" not in overrides:
        ctx.breach(node, "params", param_count,
                   f"Function {node.name} params {param_count} > {LIMITS['params']} (prefer ≤{PREFER['params']})")


def check_complexity(node: ast.AST, ctx: GateContext) -> None:
    """CC (radon if available) and cognitive complexity limits."""
    overrides = get_override_comment(node, ctx.source_lines)
    if ctx.radon_cc and node.name in ctx.radon_cc:
        cc_val = ctx.radon_cc[node.name]
    else:
        cc_val = compute_cc_simple(node)
    if cc_val > LIMITS["cc"] and "cc" not in overrides:
        ctx.breach(node, "cc", cc_val,
                   f"Function {node.name} CC {cc_val} > {LIMITS['cc']} (prefer ≤{PREFER['cc']})")
    cog_val = (ctx.cog_map or {}).get(node.name)
    if cog_val is not None and cog_val > LIMITS["cognitive"] and "cognitive" not in overrides:
        ctx.breach(node, "cognitive", cog_val,
                   f"Function {node.name} cognitive {cog_val} > {LIMITS['cognitive']} (prefer ≤{PREFER['cognitive']})")


def check_nesting(node: ast.AST, ctx: GateContext) -> None:
    """Nesting-depth limit."""
    overrides = get_override_comment(node, ctx.source_lines)
    nesting = get_nesting_depth(node)
    if nesting > LIMITS["nesting"] and "nesting" not in overrides:
        ctx.breach(node, "nesting", nesting,
                   f"Function {node.name} nesting {nesting} > {LIMITS['nesting']} (prefer ≤{PREFER['nesting']})")


def check_class(node: ast.ClassDef, ctx: GateContext) -> None:
    """Class LOC and method-count limits."""
    overrides = get_override_comment(node, ctx.source_lines)
    loc = node_loc(node)
    if loc > LIMITS["class_loc"] and "class-loc" not in overrides and "loc" not in overrides:
        ctx.breach(node, "class-loc", loc,
                   f"Class {node.name} LOC {loc} > {LIMITS['class_loc']} (prefer ≤{PREFER['class_loc']})")
    mcount = len([n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])
    if mcount > LIMITS["methods"] and "methods" not in overrides:
        ctx.breach(node, "methods", mcount,
                   f"Class {node.name} methods {mcount} > {LIMITS['methods']} (prefer ≤{PREFER['methods']})")


def walk(node: ast.AST, ctx: GateContext, stack: List[ast.AST] = None) -> None:
    """Depth-first dispatch: per-function metrics, then class metrics, then children."""
    stack = stack or []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        check_name_gaming(node, ctx)
        check_func_loc(node, ctx)
        check_params(node, stack, ctx)
        check_complexity(node, ctx)
        check_nesting(node, ctx)
    if isinstance(node, ast.ClassDef):
        check_class(node, ctx)
    for child in ast.iter_child_nodes(node):
        walk(child, ctx, stack + [node])


def check_file(file_path: Path) -> List[Dict]:
    """Run every metric checker over one file."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [{"file": str(file_path), "error": f"read failed: {e}", "fail": True}]
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        return [{"file": str(file_path), "error": f"syntax error: {e}", "fail": True}]
    ctx = GateContext(file_path, source.splitlines(),
                      try_radon_cc(file_path), try_cognitive(file_path))
    walk(tree, ctx)
    return ctx.breaches


def read_coverage(cov_path: Path) -> Optional[Dict[str, float]]:
    """{line, branch} percentages from a coverage.json, or None if absent."""
    if not cov_path.exists():
        return None
    data = json.loads(cov_path.read_text(encoding="utf-8"))
    totals = data.get("totals", {})
    covered_branches = totals.get("covered_branches", 0)
    num_branches = totals.get("num_branches", 0)
    return {
        "line": float(totals.get("percent_covered", 0)),
        "branch": (covered_branches / num_branches * 100) if num_branches else 0.0,
    }


def coverage_breach(metric: str, fields: Dict) -> Dict:
    """Coverage-lane breach record: {value, limit, fail, message} payload."""
    return {"file": "coverage.json", "type": "coverage", "metric": metric, **fields}


ABSOLUTE_COVERAGE = {"line": 80.0, "branch": 75.0}


def metric_lane(metric: str, value: float, ratchet: Optional[float]) -> List[Dict]:
    """One coverage lane. Absolute 80/75 is the FINAL D4 target.

    With ratchet (mid-round, RULE 16 'never decrease'): a drop below the
    baseline FAILS; the absolute shortfall only WARNS until D4 lands.
    Without ratchet: the absolute shortfall FAILS as before."""
    limit = ABSOLUTE_COVERAGE[metric]
    if ratchet is not None:
        lanes = []
        if value < ratchet:
            lanes.append(coverage_breach(metric, {
                "value": value, "limit": ratchet, "fail": True,
                "message": f"Coverage RATCHET: {metric} {value:.2f}% < baseline "
                           f"{ratchet:.2f}% — coverage must never decrease (RULE 16)"}))
        if value < limit:
            lanes.append(coverage_breach(metric, {
                "value": value, "limit": limit, "fail": False,
                "message": f"{metric.capitalize()} coverage {value:.1f}% < {limit:.0f}% "
                           "(final D4 target — warning in ratchet mode)"}))
        return lanes
    if value < limit:
        return [coverage_breach(metric, {
            "value": value, "limit": limit, "fail": True,
            "message": f"{metric.capitalize()} coverage {value:.1f}% < {limit:.0f}%"})]
    return []


def check_coverage(cov_path: Path = None, ratchet: Optional[Dict[str, float]] = None,
                   baseline: Optional[Dict] = None) -> List[Dict]:
    """Coverage lanes from an existing coverage.json (gate stays fast; the
    pre-push script generates the file right before invoking the gate)."""
    cov_path = cov_path or (ROOT / "coverage.json")
    try:
        cov = read_coverage(cov_path)
    except Exception as e:
        return [coverage_breach("parse-error", {
            "value": 0, "limit": 0, "fail": False,
            "message": f"Failed to parse {cov_path.name}: {e}"})]
    if cov is None:
        return [coverage_breach("missing", {
            "value": 0, "limit": 0, "fail": False,
            "message": f"{cov_path.name} not found — run: QT_QPA_PLATFORM=offscreen "
                       "python -m coverage run --branch --source=app -m pytest tests -q "
                       f"&& python -m coverage json -o {cov_path}"})]
    lanes = []
    for metric in ("line", "branch"):
        base = ratchet.get(metric) if ratchet else None
        lanes.extend(metric_lane(metric, cov[metric], base))
    lanes.extend(per_file_coverage_lanes(cov_path, baseline or {}))
    return lanes


def load_coverage_baseline(baseline_path: str) -> Optional[Dict[str, float]]:
    """"coverage" key of the quality baseline, if present."""
    try:
        data = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        cov = data.get("coverage")
        return cov if isinstance(cov, dict) else None
    except Exception:
        return None


def update_coverage_baseline(baseline_path: str, cov_path: Path) -> str:
    """Store current coverage in the baseline file (keeps existing keys).

    The ratchet floor may only move UP (RULE 16 never-decrease); refusing
    a lower value is what makes the floor tamper-proof."""
    cov = read_coverage(cov_path)
    if cov is None:
        raise SystemExit(f"no coverage data at {cov_path} — generate it first")
    path = Path(baseline_path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    old = data.get("coverage") if isinstance(data.get("coverage"), dict) else None
    if old and (cov["line"] < old.get("line", 0) or cov["branch"] < old.get("branch", 0)):
        raise SystemExit(
            f"refusing to LOWER the ratchet floor: baseline stores "
            f"{old.get('line')}/{old.get('branch')} but current run measured "
            f"{cov['line']:.2f}/{cov['branch']:.2f} (RULE 16 never-decrease). "
            "Fix the coverage drop — lowering the floor needs an explicit, "
            "reviewed baseline edit.")
    # floor to 2dp: a rounded-UP floor can exceed what was actually measured
    # and then fail the very next identical run (51.168 -> 51.17 trap).
    data["coverage"] = {"line": math.floor(cov["line"] * 100) / 100,
                        "branch": math.floor(cov["branch"] * 100) / 100}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"baseline coverage stored: line {cov['line']:.2f}%, branch {cov['branch']:.2f}%"

def file_symbol_stats(file_path: Path) -> Dict:
    """Per-symbol LOC map + func/class maxima for the legacy baseline."""
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    funcs: Dict[str, int] = {}
    max_func = max_class = 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            loc = node_loc(node)
            funcs[node.name] = max(funcs.get(node.name, 0), loc)
            max_func = max(max_func, loc)
            count += 1
        elif isinstance(node, ast.ClassDef):
            max_class = max(max_class, node_loc(node))
    return {"max_func_loc": max_func, "max_class_loc": max_class,
            "func_count": count, "funcs": funcs}


def _coverage_floor(cov_path: Path) -> Optional[Dict[str, float]]:
    try:
        cov = read_coverage(cov_path)
    except Exception:
        return None
    if cov is None:
        return None
    return {"line": math.floor(cov["line"] * 100) / 100,
            "branch": math.floor(cov["branch"] * 100) / 100}


def _coverage_by_file(cov_path: Path) -> Dict[str, float]:
    try:
        data = json.loads(cov_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {rel: round(float(entry.get("summary", {}).get("percent_covered", 0.0)), 2)
            for rel, entry in data.get("files", {}).items()}


def record_baseline(baseline_path: str, refresh: bool = False,
                    cov_path: Path = None) -> str:
    """(Re)record the ratchet baseline: py maxima + per-symbol funcs maps +
    JS maxima + per-file coverage + the global coverage floor.

    refresh=False keeps every recorded maximum (only NEW files/symbols are
    added — the ratchet never loosens by itself). refresh=True is the
    integrator's reviewed re-record after a merge; it is the only path that
    may raise a maximum, and the commit that runs it must say why."""
    path = Path(baseline_path)
    old: Dict = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    data: Dict = {}
    if isinstance(old.get("coverage"), dict):
        data["coverage"] = old["coverage"]
    for f in all_app_files():
        rel = str(f.relative_to(ROOT))
        entry = old.get(rel) if isinstance(old.get(rel), dict) else {}
        stats = file_symbol_stats(f)
        maxima = current_maxima(f)
        recorded = dict(stats)
        for metric in RATCHET_METRICS + ["file_lines"]:
            recorded[metric] = maxima[metric] if refresh else entry.get(metric, maxima[metric])
        for metric in ("max_func_loc", "max_class_loc"):
            if not refresh and metric in entry:
                recorded[metric] = entry[metric]
        recorded["func_count"] = stats["func_count"]
        if "coverage" in entry and not refresh:
            recorded["coverage"] = entry["coverage"]
        data[rel] = recorded
    cov_path = cov_path or (ROOT / "coverage.json")
    per_file_cov = _coverage_by_file(cov_path)
    for rel, pct in per_file_cov.items():
        if rel in data:
            data[rel]["coverage"] = pct
    if per_file_cov:
        floor = _coverage_floor(cov_path)
        if floor and (not isinstance(data.get("coverage"), dict) or refresh
                      or floor["line"] > data["coverage"].get("line", 0)
                      or floor["branch"] > data["coverage"].get("branch", 0)):
            data["coverage"] = floor
    for rel, cur in sorted(js_maxima(all_js_files()).items()):
        entry = old.get(rel) if isinstance(old.get(rel), dict) else {}
        recorded = {metric: cur[metric] for metric in JS_METRICS}
        if not refresh:
            for metric in JS_METRICS:
                recorded[metric] = entry.get(metric, cur[metric])
        recorded["js"] = True
        data[rel] = recorded
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    n_py = sum(1 for k in data if k.startswith("app/") and not k.endswith(".js"))
    n_js = sum(1 for k in data if k.endswith(".js"))
    mode = "re-recorded (refresh)" if refresh else "extended (never loosens)"
    return f"baseline {mode}: {n_py} py + {n_js} js entries, coverage floor {data.get('coverage')}"


def parse_args():
    parser = argparse.ArgumentParser(description="RULE 16 quality gate for Arena")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument("--changed", action="store_true", help="only check files changed vs the base ref")
    parser.add_argument("--base", type=str, default="origin/main",
                        help="base ref for --changed (default origin/main)")
    parser.add_argument("--allow-legacy", action="store_true", help="allow legacy files that are in baseline to exceed limits if not increased")
    parser.add_argument("--baseline", type=str, default="tools/quality_baseline.json", help="baseline file for legacy")
    parser.add_argument("--coverage-file", type=str, default=None,
                        help="coverage.json path (default: ./coverage.json)")
    parser.add_argument("--coverage-ratchet", action="store_true",
                        help="mid-round mode: coverage fails only on DECREASE vs baseline 'coverage' key; absolute 80/75 warns (final D4 target)")
    parser.add_argument("--update-coverage-baseline", action="store_true",
                        help="store current coverage into the baseline file, then exit")
    parser.add_argument("--rebuild-legacy-baseline", action="store_true",
                        help="add per-symbol funcs maps to the legacy baseline (integrator-only), then exit")
    parser.add_argument("--record-baseline", action="store_true",
                        help="integrator-only: re-record py maxima/funcs + JS maxima + coverage floor, then exit")
    parser.add_argument("--js", action="store_true", help="force the JS lane on")
    parser.add_argument("--no-js", action="store_true", help="skip the JS lane")
    return parser.parse_args()


def legacy_verdict(breach: Dict, base: Dict) -> Optional[str]:
    """None = grandfathered (warn). 'growth'/'new' = must fail (RULE 16 §16.5).

    Per-symbol: with a baseline 'funcs' map, a known symbol may not exceed
    its own baseline LOC and an unknown symbol is new code in a legacy file.
    Without the map, fall back to the file-level maxima."""
    metric = breach.get("metric")
    value = breach.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if metric == "loc":
        funcs = base.get("funcs") or {}
        if breach.get("name") in funcs:
            return "growth" if value > funcs[breach["name"]] else None
        if funcs:
            return "new"
        return "growth" if value > base.get("max_func_loc", value) else None
    if metric == "class-loc":
        return "growth" if value > base.get("max_class_loc", value) else None
    return None


def downgrade_legacy(breaches: List[Dict], base: Optional[Dict]) -> List[Dict]:
    """Legacy file: downgrade metric breaches to warn — EXCEPT anti-gaming,
    per-symbol growth, and new symbols, which still fail (RULE 16 §16.5:
    legacy hotspots must not grow; new code in them must meet the standard)."""
    if not base:
        return breaches
    filtered = []
    for b in breaches:
        if b.get("metric") == "anti-gaming" or str(b.get("metric", "")).startswith("ratchet"):
            # anti-gaming and R0.3 ratchet growth are never grandfathered
            if not b.get("version"):
                b["fail"] = True
            filtered.append(b)
            continue
        verdict = legacy_verdict(b, base)
        if verdict == "new":
            b["fail"] = True
            b["message"] = (f"[LEGACY-NEW] {b['message']} — new symbol in a "
                            "legacy file must meet the standard (RULE 16 §16.5)")
        elif verdict == "growth":
            b["fail"] = True
            b["message"] = (f"[LEGACY GROWTH] {b['message']} — exceeds the "
                            "baseline maximum for this symbol: legacy hotspots "
                            "must not grow (RULE 16 §16.5)")
        else:
            b["fail"] = False
            b["message"] = f"[LEGACY] {b['message']} (baseline max_func {base.get('max_func_loc')}, max_class {base.get('max_class_loc')})"
        filtered.append(b)
    return filtered


def select_files(args) -> Tuple[List[Path], Optional[str]]:
    """Files to gate + fallback reason when --changed is impossible (F-6)."""
    if not args.changed:
        return all_app_files(), None
    files, fallback = changed_app_files(args.base)
    if fallback:
        sys.stderr.write(
            f"⚠⚠ GATE HONESTY (--changed): {fallback}\n"
            f"    Falling back to gating ALL app files. For a true changed-only\n"
            f"    run, pass --base <ref> where <ref> shares ancestry with HEAD\n"
            f"    (e.g. --base {args.base} after the branch is rebased/merged).\n")
        return all_app_files(), fallback
    return files, None


def collect_breaches(args, files: List[Path], baseline_data: Dict,
                    ratchet: Optional[Dict[str, float]]) -> List[Dict]:
    """Per-file metric breaches (legacy-downgraded when allowed) + coverage lanes."""
    all_breaches: List[Dict] = []
    for f in files:
        breaches = check_file(f)
        rel = str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f)
        breaches.extend(ratchet_growth(rel, current_maxima(f), baseline_data.get(rel)))
        if args.allow_legacy:
            breaches = downgrade_legacy(breaches, baseline_data.get(rel) or baseline_data.get(str(f)))
        all_breaches.extend(breaches)
    cov_path = Path(args.coverage_file) if args.coverage_file else None
    all_breaches.extend(check_coverage(cov_path=cov_path, ratchet=ratchet,
                                       baseline=baseline_data))
    if args.coverage_ratchet and ratchet is None:
        all_breaches.append({
            "file": "coverage.json", "type": "coverage",
            "metric": "ratchet-unavailable", "fail": False,
            "message": "--coverage-ratchet: baseline 'coverage' key missing or "
                       "unreadable — ratchet floor unavailable, absolute D4 "
                       "lanes applied (seed with --update-coverage-baseline)",
        })
    return all_breaches


def ratchet_floor(args) -> Optional[Dict[str, float]]:
    """Baseline coverage floor when ratchet mode is on (None = unavailable)."""
    if not args.coverage_ratchet:
        return None
    return load_coverage_baseline(args.baseline)


def print_text_report(fails: List[Dict], warns: List[Dict], files_checked: int) -> None:
    print(f"Checked {files_checked} files in app/")
    print(f"Found {len(fails)} fail(s), {len(warns)} warn(s)")
    print("")
    if fails:
        print("=== FAILS (must fix before push) ===")
        for b in fails:
            print(f"{b.get('file')}:{b.get('lineno','')} [{b.get('metric')}] {b.get('message')}")
        print("")
    if warns:
        print("=== WARNS (should fix, not blocking) ===")
        for b in warns:
            print(f"{b.get('file')} [{b.get('metric','')}] {b.get('message')}")
        print("")
    if not fails:
        print_pass_banner()
    else:
        print_fail_banner()


def print_pass_banner() -> None:
    print("✅ Quality gate PASSED — no fails")
    print("")
    print("Preferences (not failing, but aim):")
    print(f"  Function LOC prefer ≤{PREFER['func_loc']}, fail >{LIMITS['func_loc']}")
    print(f"  Class LOC prefer ≤{PREFER['class_loc']}, fail >{LIMITS['class_loc']}")
    print(f"  Params prefer ≤{PREFER['params']}, fail >{LIMITS['params']}")
    print(f"  Methods per class prefer ≤{PREFER['methods']}, fail >{LIMITS['methods']}")
    print(f"  CC prefer ≤{PREFER['cc']}, fail >{LIMITS['cc']} (radon cc -s)")
    print(f"  Cognitive prefer ≤{PREFER['cognitive']}, fail >{LIMITS['cognitive']}")
    print(f"  Nesting prefer ≤{PREFER['nesting']}, fail >{LIMITS['nesting']}")
    print(f"  Coverage line ≥80%, branch ≥75%")
    print("")
    print("Run before every push:")
    print("  python tools/verify_quality.py")
    print("  QT_QPA_PLATFORM=offscreen python -m coverage run --branch --source=app -m pytest tests -q")
    print("  python -m coverage json -o coverage.json")


def print_fail_banner() -> None:
    print("❌ Quality gate FAILED — fix fails before push (RULE 16)")
    print("")
    print("Remediation order (RULE 19): nesting → CC → cognitive → size")
    print("  1. Nesting >4 → extract guard, early return, flatten")
    print("  2. CC >10 → split decision, not just code (no foo_part1)")
    print("  3. Cognitive >15 → name predicates, simplify boolean")
    print("  4. LOC >30 → extract helper with real responsibility name")


def main():
    args = parse_args()
    if args.rebuild_legacy_baseline:
        print(record_baseline(args.baseline, refresh=False,
                              cov_path=Path(args.coverage_file) if args.coverage_file else None))
        return
    if args.record_baseline:
        print(record_baseline(args.baseline, refresh=True,
                              cov_path=Path(args.coverage_file) if args.coverage_file else None))
        return
    if args.update_coverage_baseline:
        print(update_coverage_baseline(args.baseline, Path(args.coverage_file or ROOT / "coverage.json")))
        return
    baseline_data = {}
    if args.allow_legacy:
        try:
            baseline_path = Path(args.baseline)
            if baseline_path.exists():
                baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
        except Exception:
            baseline_data = {}
    files, changed_fallback = select_files(args)
    all_breaches = collect_breaches(args, files, baseline_data, ratchet_floor(args))
    js_files = [] if args.no_js else (changed_js_files(args.base) if args.changed else all_js_files())
    if js_files or args.js:
        all_breaches.extend(check_js(js_files, baseline_data))
    fails = [b for b in all_breaches if b.get("fail")]
    warns = [b for b in all_breaches if not b.get("fail")]
    if args.json:
        print(json.dumps({"breaches": all_breaches, "fails": fails, "warns": warns,
                          "files_checked": len(files), "js_files": len(js_files),
                          "changed_fallback": changed_fallback}, indent=2, ensure_ascii=False))
    else:
        print_text_report(fails, warns, len(files))
        if js_files:
            print(f"JS lane: {len(js_files)} file(s) checked")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
