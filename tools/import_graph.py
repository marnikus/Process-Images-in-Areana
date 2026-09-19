#!/usr/bin/env python3
"""Import-graph audit — proves which app modules are dead (RULE 16.4 dead code).

A module is DEAD when no production module (app/**) imports it and it is not
an entry point (app.main). Modules imported only by tests are TEST-ONLY.

Usage:
    python tools/import_graph.py            # table for all app modules
    python tools/import_graph.py --dead     # only dead / test-only, exit 1 if any
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "app"
ENTRY_POINTS = {"app.main"}
EXCLUDED_PARTS = {"node_modules", "__pycache__", ".venv", "Old App", ".git"}

# Deliberately test-only modules (SYSTEM_OF_RECORD §8 mandates their tests):
# app/services/verification.py — RULE 15 download-validation tests
# app/core/state_machine.py — RULE 7 state-machine 00-22 tests
# Flagged for a future batch when their logic is wired into the live path.
# See docs/archive/2026-09-19-dead-code-quality-batch/design.md.
DOCUMENTED_TEST_ONLY = {"app.services.verification", "app.core.state_machine"}


def module_of(path: Path) -> str:
    rel = path.with_suffix("").relative_to(ROOT).as_posix().replace("/", ".")
    return rel[:-9] if rel.endswith(".__init__") else rel


def find_modules() -> tuple[dict[str, Path], set[str]]:
    mods: dict[str, Path] = {}
    pkgs: set[str] = set()
    for p in sorted(ROOT.rglob("*.py")):
        if any(part in EXCLUDED_PARTS for part in p.parts):
            continue
        mod = module_of(p)
        if mod.endswith(".__init__") or p.name == "__init__.py":
            pkgs.add(module_of(p))
        mods[module_of(p)] = p
    return mods, pkgs


def resolve(from_mod: str, level: int, modname: str | None, pkgs: set[str]) -> str | None:
    if level == 0:
        return modname
    base = from_mod.split(".")
    if from_mod not in pkgs:
        base = base[:-1]
    if level > 1:
        base = base[: -(level - 1)]
    return ".".join(base + ([modname] if modname else []))


def import_graph(mods: dict[str, Path], pkgs: set[str]) -> dict[str, set[str]]:
    imports: dict[str, set[str]] = {}
    for mod, path in mods.items():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                target = resolve(mod, node.level or 0, node.module, pkgs)
                targets = [target] if target else []
            else:
                continue
            for t in targets:
                imports.setdefault(t, set()).add(mod)
    return imports


def classify(mod: str, imports: dict[str, set[str]], mods: dict[str, Path]) -> str:
    if mod in ENTRY_POINTS:
        return "entry"
    children = [m for m in mods if m.startswith(mod + ".")]
    if children:  # package: verdict follows its most-advanced child
        verdicts = {classify(c, imports, mods) for c in children}
        if "alive" in verdicts or "entry" in verdicts:
            return "alive"
        return "test-only" if "test-only" in verdicts else "DEAD"
    importers = imports.get(mod, set())
    if not importers:
        return "DEAD"
    prod = {i for i in importers if i.startswith(APP + ".") or i == APP}
    if not prod:
        return "test-only"
    return "alive"


def dead_closure(mods: dict[str, Path], imports: dict[str, set[str]]) -> set[str]:
    """Fixpoint: a module is dead if nothing alive reaches it (only dead/test importers)."""
    dead: set[str] = set()
    changed = True
    while changed:
        changed = False
        for mod in mods:
            if mod in ENTRY_POINTS or mod in dead or mod in pkgs_of(mods):
                continue
            importers = imports.get(mod, set())
            reachable = {i for i in importers if i not in dead and not i.startswith(("tests", "tools"))}
            if not reachable and mod not in ENTRY_POINTS:
                dead.add(mod)
                changed = True
    return dead


def pkgs_of(mods: dict[str, Path]) -> set[str]:
    return {m for m in mods if mods[m].name == "__init__.py"}


def _production_modules(mods: dict) -> list:
    return [m for m in sorted(mods)
            if m.startswith(APP + ".") and m not in ENTRY_POINTS and mods[m].name != "__init__.py"]


def _verdict_line(mod: str, dead: set, dead_only: bool, imports: dict, mods: dict):
    """(line, is_dead). line None = suppressed in --dead mode."""
    importers = sorted(imports.get(mod, set()))
    if mod in dead:
        if mod in DOCUMENTED_TEST_ONLY:
            return f"doc-kept   {mod:55s} test-only by design (SYSTEM_OF_RECORD §8)", False
        direct = "no importers" if not importers else "only via dead/test modules"
        return f"DEAD       {mod:55s} {direct}; importers={importers or '—'}", True
    if dead_only:
        return None, False
    verdict = classify(mod, imports, mods)
    return f"{verdict:10s} {mod:55s} importers={importers or '—'}", False


def main() -> int:
    dead_only = "--dead" in sys.argv
    mods, pkgs = find_modules()
    imports = import_graph(mods, pkgs)
    dead = dead_closure(mods, imports)
    bad = 0
    for mod in _production_modules(mods):
        line, is_dead = _verdict_line(mod, dead, dead_only, imports, mods)
        if line:
            print(line)
        bad += int(is_dead)
    if dead_only and bad:
        print(f"\n{bad} DEAD module(s) (production closure) — remove or wire (RULE 16.4)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
