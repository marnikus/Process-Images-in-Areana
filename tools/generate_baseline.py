#!/usr/bin/env python3
"""Generate quality_baseline.json with per-metric maxima per file (R0.3 ratchet)"""

from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).parent))
from verify_quality import find_py_files, check_py_file, find_js_files
import subprocess

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "ui" / "web"

def main():
    baseline = {}
    for fp in find_py_files(changed=False):
        _, cur = check_py_file(fp)
        rel = str(fp.relative_to(ROOT))
        # also store func_count
        try:
            import ast
            src = fp.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
            fcount = len([n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])
        except Exception:
            fcount = 0
        baseline[rel] = {
            "max_func_loc": cur.get("max_func_loc", 0),
            "max_class_loc": cur.get("max_class_loc", 0),
            "max_methods": cur.get("max_methods", 0),
            "max_cc": cur.get("max_cc", 0),
            "max_cog": cur.get("max_cog", 0),
            "max_nest": cur.get("max_nest", 0),
            "max_params": cur.get("max_params", 0),
            "file_lines": cur.get("file_lines", 0),
            "func_count": fcount,
        }
    # JS baseline
    try:
        tool = ROOT / "tools" / "js_metrics.js"
        out = subprocess.check_output(["node", str(tool), str(WEB), "--json"], text=True, timeout=20)
        data = json.loads(out)
        # group by file
        from collections import defaultdict
        per_file = defaultdict(list)
        file_lines = {}
        for e in data:
            if e.get("isFile"):
                file_lines[e["file"]] = e.get("fileLines", 0)
            else:
                if not e.get("error"):
                    per_file[e["file"]].append(e)
        for f, entries in per_file.items():
            max_loc = max([x.get("loc", 0) for x in entries], default=0)
            max_cc = max([x.get("cc", 0) for x in entries], default=0)
            max_nest = max([x.get("depth", 0) for x in entries], default=0)
            max_params = max([x.get("params", 0) for x in entries], default=0)
            baseline[f] = {
                "max_func_loc": max_loc,
                "max_cc": max_cc,
                "max_nest": max_nest,
                "max_params": max_params,
                "file_lines": file_lines.get(f, 0),
                "func_count": len(entries),
                "js": True,
            }
        # also files with only fileLines
        for f, fl in file_lines.items():
            if f not in baseline:
                baseline[f] = {"file_lines": fl, "func_count": 0, "js": True}
    except Exception as e:
        print(f"JS baseline failed: {e}", file=sys.stderr)

    # Coverage per file baseline (R0.3 per-file coverage ratchet)
    try:
        cov_path = ROOT / "coverage.json"
        if cov_path.exists():
            cov_data = json.loads(cov_path.read_text(encoding="utf-8"))
            for fp, data in cov_data.get("files", {}).items():
                rel = fp
                # coverage.json paths may be absolute or relative; normalize to app/...
                if "app/" in fp:
                    rel = fp[fp.find("app/"):]
                if rel in baseline:
                    baseline[rel]["coverage"] = data.get("summary", {}).get("percent_covered", 0)
                else:
                    # store coverage even if not in py files list (e.g., generated)
                    baseline[rel] = baseline.get(rel, {})
                    baseline[rel]["coverage"] = data.get("summary", {}).get("percent_covered", 0)
    except Exception as e:
        print(f"Coverage baseline failed: {e}", file=sys.stderr)

    out_path = ROOT / "tools" / "quality_baseline.json"
    out_path.write_text(json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(baseline)} entries to {out_path}")

if __name__ == "__main__":
    main()
