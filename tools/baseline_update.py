#!/usr/bin/env python3
"""Regenerate tools/quality_baseline.json (v2) from a CLEAN tree.

Baseline v2 (design.md D6):
  * per-symbol Python metrics: functions {name: {loc, params, cc, cognitive, nesting}},
    classes {name: {loc, methods}}  — qualified names: module fns "name", methods "Class.name"
  * file maxima (compat) + per-file line coverage % from coverage.json
  * per-symbol JS metrics for app/ui/web/js/** (via tools/js_gate.mjs --emit-baseline)

Run on a tree you are willing to freeze as the new "no worse than this" floor:
    python -m coverage run --branch --source=app -m pytest tests -q
    python -m coverage json -o coverage.json
    python tools/baseline_update.py [--root DIR] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_quality import DEFAULT_ROOT, analyze_file, find_py_files  # noqa: E402


def py_coverage_map(root: Path) -> dict[str, float]:
    cov_path = root / "coverage.json"
    if not cov_path.exists():
        return {}
    try:
        data = json.loads(cov_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, float] = {}
    for rel, fdata in (data.get("files") or {}).items():
        pct = fdata.get("summary", {}).get("percent_covered")
        if pct is not None:
            out[rel] = round(float(pct), 2)
    return out


def js_baseline(root: Path) -> dict:
    script = Path(__file__).resolve().parent / "js_gate.mjs"
    try:
        out = subprocess.check_output(
            ["node", str(script), "--root", str(root), "--emit-baseline"],
            text=True, stderr=subprocess.DEVNULL)
        return json.loads(out).get("js", {})
    except Exception as e:
        print(f"warning: JS baseline skipped ({e})", file=sys.stderr)
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate quality baseline v2")
    parser.add_argument("--root", type=str, default=None)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else DEFAULT_ROOT
    out_path = Path(args.out) if args.out else root / "tools" / "quality_baseline.json"

    cov = py_coverage_map(root)
    files: dict = {}
    for p in find_py_files(root):
        rel = str(p.relative_to(root))
        try:
            table = analyze_file(p)
        except Exception as e:
            print(f"warning: skipping {rel}: {e}", file=sys.stderr)
            continue
        fns = table.get("functions") or {}
        cls = table.get("classes") or {}
        entry = {
            "functions": fns,
            "classes": cls,
            "max_func_loc": max((v["loc"] for v in fns.values()), default=0),
            "max_class_loc": max((v["loc"] for v in cls.values()), default=0),
            "func_count": len(fns),
        }
        if rel in cov:
            entry["coverage"] = cov[rel]
        files[rel] = entry

    baseline = {
        "version": 2,
        "generated_from": str(root),
        "files": files,
        "js": js_baseline(root),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(baseline, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n_cov = sum(1 for v in files.values() if "coverage" in v)
    print(f"baseline v2 written: {out_path}")
    print(f"  python files: {len(files)} ({n_cov} with coverage)")
    print(f"  js files: {len(baseline['js'])}")


if __name__ == "__main__":
    main()
