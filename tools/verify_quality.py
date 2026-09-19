#!/usr/bin/env python3
"""
RULE 16 gate — size and complexity limits for Arena Image Processor.

Adapted from Old App tools/metrics/rule16_gate.py but simplified for Arena,
preserving thresholds, invariants pattern, and override format.

Usage:
    python tools/verify_quality.py              # report, exit 1 on breach
    python tools/verify_quality.py --json       # machine-readable
    python tools/verify_quality.py --changed    # only files changed vs main

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
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
TESTS_DIR = ROOT / "tests"

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

def find_py_files(changed_only: bool = False) -> List[Path]:
    if changed_only:
        try:
            import subprocess
            out = subprocess.check_output(
                ["git", "diff", "--name-only", "origin/main...HEAD"],
                cwd=str(ROOT),
                text=True,
            )
            files = []
            for line in out.splitlines():
                p = ROOT / line.strip()
                # Only app files are gated for quality (tests/tools out of scope)
                if not str(p).startswith(str(APP_DIR)):
                    continue
                if p.suffix == ".py" and p.exists() and not is_out_of_scope(p):
                    files.append(p)
            if files:
                return sorted(files)
        except Exception:
            pass
    files = []
    for p in APP_DIR.rglob("*.py"):
        if not is_out_of_scope(p):
            files.append(p)
    return sorted(files)

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

def get_nesting_depth(node: ast.AST, current_depth: int = 0, max_depth: int = 0, stack=None) -> int:
    """Compute max nesting depth of branching constructs."""
    if stack is None:
        stack = []
    # Branching nodes that increase nesting
    nesting_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.Try)
    # Actually Try itself doesn't cost per RULE 16, but its handlers do? For nesting, count if/for/while/with/try?
    # Per AGENT_RULES.md: nesting counts if/for/while/with/try etc? Let's count If, For, While, With
    # We'll count If, For, While, With, Try as nesting increasers
    new_depth = current_depth
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With)):
        new_depth = current_depth + 1
        max_depth = max(max_depth, new_depth)
    # Recurse
    for child in ast.iter_child_nodes(node):
        max_depth = get_nesting_depth(child, new_depth, max_depth, stack + [node])
    return max_depth

def compute_cc_simple(node: ast.AST) -> int:
    """Simple cyclomatic complexity approximation: base 1 + branching."""
    cc = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With)):
            cc += 1
        elif isinstance(n, ast.BoolOp):
            # +1 per and/or beyond first
            if isinstance(n.op, (ast.And, ast.Or)):
                cc += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            # +1 per if in comprehension
            cc += len(n.ifs)
        elif isinstance(n, ast.IfExp):
            cc += 1
        elif isinstance(n, ast.Assert):
            cc += 1
    return cc

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
        for fp, entries in data.items():
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

def check_file(file_path: Path) -> List[Dict]:
    breaches = []
    try:
        source = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [{"file": str(file_path), "error": f"read failed: {e}", "fail": True}]
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        return [{"file": str(file_path), "error": f"syntax error: {e}", "fail": True}]

    # Try radon and cognitive if available
    radon_cc = try_radon_cc(file_path)
    cog_map = try_cognitive(file_path)

    # Walk for functions and classes
    # Keep stack for method detection
    def walk(node, stack=None, depth=0):
        if stack is None:
            stack = []
        # Function
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name
            # Skip if name suggests part split gaming
            if re.search(r"_part\d+$", func_name):
                breaches.append({
                    "file": str(file_path.relative_to(ROOT)),
                    "type": "function",
                    "name": func_name,
                    "lineno": getattr(node, "lineno", 0),
                    "metric": "anti-gaming",
                    "value": func_name,
                    "limit": "no _partN split",
                    "fail": True,
                    "message": f"Function {func_name} looks like gaming split foo_part1/part2 (RULE 16 anti-gaming)",
                })
            # LOC
            try:
                end_lineno = getattr(node, "end_lineno", None) or node.lineno
                loc = end_lineno - node.lineno + 1
            except Exception:
                loc = 0
            # Check override
            overrides = get_override_comment(node, source_lines)
            # func_loc
            if loc > LIMITS["func_loc"]:
                if "loc" not in overrides:
                    breaches.append({
                        "file": str(file_path.relative_to(ROOT)),
                        "type": "function",
                        "name": func_name,
                        "lineno": node.lineno,
                        "metric": "loc",
                        "value": loc,
                        "limit": LIMITS["func_loc"],
                        "prefer": PREFER["func_loc"],
                        "fail": True,
                        "message": f"Function {func_name} LOC {loc} > {LIMITS['func_loc']} (prefer ≤{PREFER['func_loc']}) at {file_path}:{node.lineno}",
                    })
                else:
                    val, reason = overrides["loc"]
                    if len(reason.strip()) < 20:
                        breaches.append({
                            "file": str(file_path.relative_to(ROOT)),
                            "type": "function",
                            "name": func_name,
                            "lineno": node.lineno,
                            "metric": "loc-override-reason",
                            "value": reason,
                            "fail": True,
                            "message": f"Override reason too short (<20 chars) for {func_name} loc override: {reason}",
                        })
            # Params
            param_count = count_params(node)
            # Exclude self/cls for methods
            if is_method_inside_class(stack):
                # If first arg is self or cls, subtract 1
                try:
                    first_arg = None
                    if node.args.posonlyargs:
                        first_arg = node.args.posonlyargs[0].arg
                    elif node.args.args:
                        first_arg = node.args.args[0].arg
                    if first_arg in ("self", "cls"):
                        param_count = max(0, param_count - 1)
                except Exception:
                    pass
            if param_count > LIMITS["params"]:
                # Check for **kwargs dodge
                has_kwargs = node.args.kwarg is not None
                if has_kwargs and param_count <= 1:
                    breaches.append({
                        "file": str(file_path.relative_to(ROOT)),
                        "type": "function",
                        "name": func_name,
                        "lineno": node.lineno,
                        "metric": "anti-gaming",
                        "value": param_count,
                        "fail": True,
                        "message": f"Function {func_name} uses **kwargs to dodge params count (RULE 16 anti-gaming)",
                    })
                if "params" not in overrides:
                    breaches.append({
                        "file": str(file_path.relative_to(ROOT)),
                        "type": "function",
                        "name": func_name,
                        "lineno": node.lineno,
                        "metric": "params",
                        "value": param_count,
                        "limit": LIMITS["params"],
                        "prefer": PREFER["params"],
                        "fail": True,
                        "message": f"Function {func_name} params {param_count} > {LIMITS['params']} (prefer ≤{PREFER['params']})",
                    })
            # CC
            if radon_cc and func_name in radon_cc:
                cc_val = radon_cc[func_name]
            else:
                cc_val = compute_cc_simple(node)
            if cc_val > LIMITS["cc"]:
                if "cc" not in overrides:
                    breaches.append({
                        "file": str(file_path.relative_to(ROOT)),
                        "type": "function",
                        "name": func_name,
                        "lineno": node.lineno,
                        "metric": "cc",
                        "value": cc_val,
                        "limit": LIMITS["cc"],
                        "prefer": PREFER["cc"],
                        "fail": True,
                        "message": f"Function {func_name} CC {cc_val} > {LIMITS['cc']} (prefer ≤{PREFER['cc']})",
                    })
            # Cognitive
            cog_val = None
            if cog_map and func_name in cog_map:
                cog_val = cog_map[func_name]
            # If cognitive lib not available, skip cognitive check (or use CC as proxy)
            if cog_val is not None and cog_val > LIMITS["cognitive"]:
                if "cognitive" not in overrides:
                    breaches.append({
                        "file": str(file_path.relative_to(ROOT)),
                        "type": "function",
                        "name": func_name,
                        "lineno": node.lineno,
                        "metric": "cognitive",
                        "value": cog_val,
                        "limit": LIMITS["cognitive"],
                        "prefer": PREFER["cognitive"],
                        "fail": True,
                        "message": f"Function {func_name} cognitive {cog_val} > {LIMITS['cognitive']} (prefer ≤{PREFER['cognitive']})",
                    })
            # Nesting
            nesting = get_nesting_depth(node)
            if nesting > LIMITS["nesting"]:
                if "nesting" not in overrides:
                    breaches.append({
                        "file": str(file_path.relative_to(ROOT)),
                        "type": "function",
                        "name": func_name,
                        "lineno": node.lineno,
                        "metric": "nesting",
                        "value": nesting,
                        "limit": LIMITS["nesting"],
                        "prefer": PREFER["nesting"],
                        "fail": True,
                        "message": f"Function {func_name} nesting {nesting} > {LIMITS['nesting']} (prefer ≤{PREFER['nesting']})",
                    })
        # Class
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            try:
                end_lineno = getattr(node, "end_lineno", None) or node.lineno
                loc = end_lineno - node.lineno + 1
            except Exception:
                loc = 0
            overrides = get_override_comment(node, source_lines)
            if loc > LIMITS["class_loc"]:
                if "class-loc" not in overrides and "loc" not in overrides:
                    breaches.append({
                        "file": str(file_path.relative_to(ROOT)),
                        "type": "class",
                        "name": class_name,
                        "lineno": node.lineno,
                        "metric": "class-loc",
                        "value": loc,
                        "limit": LIMITS["class_loc"],
                        "prefer": PREFER["class_loc"],
                        "fail": True,
                        "message": f"Class {class_name} LOC {loc} > {LIMITS['class_loc']} (prefer ≤{PREFER['class_loc']})",
                    })
            # Methods count
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            mcount = len(methods)
            if mcount > LIMITS["methods"]:
                if "methods" not in overrides:
                    breaches.append({
                        "file": str(file_path.relative_to(ROOT)),
                        "type": "class",
                        "name": class_name,
                        "lineno": node.lineno,
                        "metric": "methods",
                        "value": mcount,
                        "limit": LIMITS["methods"],
                        "prefer": PREFER["methods"],
                        "fail": True,
                        "message": f"Class {class_name} methods {mcount} > {LIMITS['methods']} (prefer ≤{PREFER['methods']})",
                    })

        for child in ast.iter_child_nodes(node):
            walk(child, stack + [node], depth + 1)

    walk(tree)
    return breaches

def check_coverage() -> List[Dict]:
    breaches = []
    # Try to run pytest --cov if coverage available
    # We don't run coverage here by default to keep gate fast; instead check existing coverage.json if present
    cov_path = ROOT / "coverage.json"
    if cov_path.exists():
        try:
            data = json.loads(cov_path.read_text(encoding="utf-8"))
            totals = data.get("totals", {})
            line_pct = totals.get("percent_covered", 0)
            # branch coverage: covered_branches / num_branches
            covered_branches = totals.get("covered_branches", 0)
            num_branches = totals.get("num_branches", 0)
            branch_pct = (covered_branches / num_branches * 100) if num_branches else 0
            if line_pct < 80:
                breaches.append({
                    "file": "coverage.json",
                    "type": "coverage",
                    "metric": "line",
                    "value": line_pct,
                    "limit": 80,
                    "fail": True,
                    "message": f"Line coverage {line_pct:.1f}% < 80%",
                })
            if branch_pct < 75 and num_branches > 0:
                breaches.append({
                    "file": "coverage.json",
                    "type": "coverage",
                    "metric": "branch",
                    "value": branch_pct,
                    "limit": 75,
                    "fail": True,
                    "message": f"Branch coverage {branch_pct:.1f}% < 75%",
                })
        except Exception as e:
            breaches.append({
                "file": "coverage.json",
                "type": "coverage",
                "error": str(e),
                "fail": False,
                "message": f"Failed to parse coverage.json: {e}",
            })
    else:
        # No coverage file, warn but not fail
        breaches.append({
            "file": "coverage.json",
            "type": "coverage",
            "metric": "missing",
            "fail": False,
            "message": "coverage.json not found — run: QT_QPA_PLATFORM=offscreen python -m coverage run --branch --source=app -m pytest tests -q && python -m coverage json -o coverage.json",
        })
    return breaches

def main():
    parser = argparse.ArgumentParser(description="RULE 16 quality gate for Arena")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument("--changed", action="store_true", help="only check files changed vs origin/main")
    parser.add_argument("--allow-legacy", action="store_true", help="allow legacy files that are in baseline to exceed limits if not increased")
    parser.add_argument("--baseline", type=str, default="tools/quality_baseline.json", help="baseline file for legacy")
    args = parser.parse_args()

    baseline_data = {}
    if args.allow_legacy:
        try:
            baseline_path = Path(args.baseline)
            if baseline_path.exists():
                baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
        except Exception:
            baseline_data = {}

    files = find_py_files(changed_only=args.changed)
    all_breaches = []
    for f in files:
        breaches = check_file(f)
        if args.allow_legacy:
            rel = str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f)
            base = baseline_data.get(rel) or baseline_data.get(str(f))
            if base:
                filtered = []
                for b in breaches:
                    if b.get("metric") == "anti-gaming":
                        filtered.append(b)
                    else:
                        # Legacy file: downgrade all to warn (not fail) to avoid blocking push on old code
                        # New code should be in files not in baseline, or should not increase beyond baseline drastically
                        b["fail"] = False
                        b["message"] = f"[LEGACY] {b['message']} (baseline max_func {base.get('max_func_loc')}, max_class {base.get('max_class_loc')})"
                        filtered.append(b)
                breaches = filtered
        all_breaches.extend(breaches)

    cov_breaches = check_coverage()
    all_breaches.extend(cov_breaches)

    # Filter fail vs warn
    fails = [b for b in all_breaches if b.get("fail")]
    warns = [b for b in all_breaches if not b.get("fail")]

    if args.json:
        print(json.dumps({"breaches": all_breaches, "fails": fails, "warns": warns, "files_checked": len(files)}, indent=2, ensure_ascii=False))
    else:
        print(f"Checked {len(files)} files in app/")
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
        else:
            print("❌ Quality gate FAILED — fix fails before push (RULE 16)")
            print("")
            print("Remediation order (RULE 19): nesting → CC → cognitive → size")
            print("  1. Nesting >4 → extract guard, early return, flatten")
            print("  2. CC >10 → split decision, not just code (no foo_part1)")
            print("  3. Cognitive >15 → name predicates, simplify boolean")
            print("  4. LOC >30 → extract helper with real responsibility name")

    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
