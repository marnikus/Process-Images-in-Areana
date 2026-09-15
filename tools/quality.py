"""Executable Rule 16 checks for new production code; missing tools fail at import."""

import ast
import json
from pathlib import Path

from cognitive_complexity.api import get_cognitive_complexity
from radon.complexity import cc_visit

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
NESTING = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.TryStar,
    ast.Match,
)
BANNED_DOMAIN_IMPORTS = {
    "PySide6",
    "sqlite3",
    "aiosqlite",
    "socket",
    "pathlib",
    "os",
    "subprocess",
    "aiohttp",
    "websockets",
    "backend",
    "services",
    "actions",
    "stores",
    "app",
}


def _parameters(node):
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    count = len(positional) + len(args.kwonlyargs) + bool(args.vararg) + bool(args.kwarg)
    if positional and positional[0].arg in {"self", "cls"}:
        count -= 1
    return count


def _nesting(node, depth=0):
    depth += isinstance(node, NESTING)
    children = (child for child in ast.iter_child_nodes(node) if not isinstance(child, FUNCTIONS))
    return max([depth, *(_nesting(child, depth) for child in children)])


def inspect_source(source, *, domain=False, workspace=False):
    """Return violations; no legacy baselines, silent dependency skips or auto-waivers."""
    tree = ast.parse(source)
    failures = []
    for node in ast.walk(tree):
        if isinstance(node, FUNCTIONS):
            metrics = {
                "function lines": (node.end_lineno - node.lineno + 1, 30),
                "parameters": (_parameters(node), 4),
                "cognitive": (get_cognitive_complexity(node), 15),
                "nesting": (_nesting(node), 4),
            }
        elif isinstance(node, ast.ClassDef):
            metrics = {
                "class lines": (node.end_lineno - node.lineno + 1, 150),
                "methods": (sum(isinstance(child, FUNCTIONS) for child in node.body), 15),
            }
        else:
            continue
        for name, (value, limit) in metrics.items():
            if value > limit:
                failures.append(f"line {node.lineno} {node.name}: {name} {value} > {limit}")
    pending = list(cc_visit(source))
    while pending:
        item = pending.pop()
        pending.extend(getattr(item, "methods", []))
        pending.extend(getattr(item, "closures", []))
        if item.complexity > 10:
            failures.append(f"line {item.lineno} {item.name}: CC {item.complexity} > 10")
    if domain:
        failures.extend(_domain_imports(tree, workspace))
    return failures


def _domain_imports(tree, workspace=False):
    failures = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            internal_infrastructure = name.startswith("image_queue.") and not (
                name == "image_queue.domain"
                or name.startswith("image_queue.domain.")
                or (workspace and name.startswith("image_queue.workspace."))
            )
            if name.split(".")[0] in BANNED_DOMAIN_IMPORTS or internal_infrastructure:
                failures.append(f"line {node.lineno}: forbidden domain import {name}")
    return failures


def check_production(root):
    failures = []
    files = sorted(root.rglob("*.py"))
    if not files:
        return ["No production Python found; check scope"]
    for path in files:
        failures.extend(
            f"{path}: {item}"
            for item in inspect_source(
                path.read_text(encoding="utf-8"),
                domain="domain" in path.parts or "workspace" in path.parts,
                workspace="workspace" in path.parts,
            )
        )
    return failures


def coverage_failures(report):
    """Independent statement/branch floors on domain, not a blended percentage."""
    summaries = [
        data["summary"]
        for name, data in report["files"].items()
        if "/domain/" in name.replace("\\", "/")
    ]
    if not summaries:
        return ["No domain coverage data; refusing an empty passing gate"]
    failures = []
    for kind, covered, total, floor in [
        ("statements", "covered_lines", "num_statements", 90),
        ("branches", "covered_branches", "num_branches", 85),
    ]:
        denominator = sum(summary[total] for summary in summaries)
        numerator = sum(summary[covered] for summary in summaries)
        percentage = 100 * numerator / denominator if denominator else 100
        print(f"Domain {kind}: {percentage:.2f}% (floor {floor}%)")
        if percentage < floor:
            failures.append(f"Domain {kind}: {percentage:.2f}% < {floor}%")
    return failures


if __name__ == "__main__":
    errors = check_production(Path("src/image_queue"))
    report = Path("coverage/coverage.json")
    if not report.exists():
        errors.append("Missing fresh coverage report: run tools/check.py")
    else:
        coverage = json.loads(report.read_text(encoding="utf-8"))
        errors.extend(coverage_failures(coverage))
        for package in ("workspace", "persistence", "browser", "scanning", "automation"):
            projected = {
                "files": {
                    name.replace("\\", "/").replace(f"/{package}/", "/domain/"): data
                    for name, data in coverage["files"].items()
                    if f"/{package}/" in name.replace("\\", "/")
                }
            }
            print(f"Checking {package} coverage:")
            errors.extend(coverage_failures(projected))
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))
