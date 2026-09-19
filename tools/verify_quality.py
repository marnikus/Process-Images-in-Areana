#!/usr/bin/env python3
"""
RULE 16 gate — size/complexity + JS gate + baseline ratchet + coverage
R0.2 JS gate (acorn), R0.3 ratchet per-metric, R0.4 vulture/jscpd/coverage lanes
"""

from __future__ import annotations
import argparse
import ast
import json
import re
import sys
import subprocess
from pathlib import Path
from collections import Counter
from typing import List, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
WEB = ROOT / "app" / "ui" / "web"

LIMITS = {"func_loc": 30, "class_loc": 150, "params": 4, "methods": 15, "cc": 10, "cognitive": 15, "nesting": 4}
PREFER = {"func_loc": 20, "class_loc": 120, "params": 3, "methods": 10, "cc": 7, "cognitive": 10, "nesting": 3}
OUT_RE = [r"^tests/", r"^tools/", r"^docs/", r"/__pycache__/", r"\.pyc$", r"config/", r"research/"]
OVERRIDE_RE = re.compile(r"quality-override:\s*(?P<m>loc|class-loc|params|methods|cc|cognitive|nesting|coverage|vulture|dup)\s*=\s*(?P<v>\S+)\s+reason=(?P<r>.+)", re.I)

def out_of_scope(p: Path) -> bool:
    s = str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
    return any(re.search(x, s) for x in OUT_RE)

def git_base() -> Optional[str]:
    try:
        b = subprocess.check_output(["git", "merge-base", "origin/main", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        if b:
            return b
    except Exception:
        pass
    return None

def find_changed_py() -> List[Path]:
    # Always include working tree changes (unstaged + staged) + untracked
    try:
        out_wt = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
        try:
            untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
            out_wt += "\n" + untracked
        except Exception:
            pass
        res_wt = []
        for line in out_wt.splitlines():
            if not line.strip():
                continue
            p = ROOT / line.strip()
            if str(p).startswith(str(APP)) and p.suffix == ".py" and p.exists() and not out_of_scope(p):
                res_wt.append(p)
        if res_wt:
            return sorted(set(res_wt))
    except Exception:
        pass
    base = git_base()
    refs = []
    if base:
        refs.append(f"{base}..HEAD")
        refs.append("origin/main..HEAD")
    refs.extend(["HEAD~1..HEAD", "HEAD~2..HEAD", "HEAD~3..HEAD"])
    for ref in refs:
        try:
            out = subprocess.check_output(["git", "diff", "--name-only", ref], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
            try:
                untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
                out += "\n" + untracked
            except Exception:
                pass
            res = []
            for line in out.splitlines():
                if not line.strip():
                    continue
                p = ROOT / line.strip()
                if str(p).startswith(str(APP)) and p.suffix == ".py" and p.exists() and not out_of_scope(p):
                    res.append(p)
            total_py = len(list(APP.rglob("*.py")))
            if len(res) > total_py * 0.5:
                continue
            if ref.startswith("HEAD~"):
                return sorted(set(res))
            if len(res) == 0:
                return []
            return sorted(set(res))
        except Exception:
            continue
    return []

def find_py_files(changed=False) -> List[Path]:
    if changed:
        # In changed mode, return exactly what find_changed returns, even if empty (means no py changed)
        return find_changed_py()
    return sorted([p for p in APP.rglob("*.py") if not out_of_scope(p)])

def find_js_files(changed=False) -> List[Path]:
    if changed:
        try:
            out_wt = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
            try:
                untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
                out_wt += "\n" + untracked
            except Exception:
                pass
            res_wt = []
            for line in out_wt.splitlines():
                if not line.strip():
                    continue
                p = ROOT / line.strip()
                if str(p).startswith(str(WEB)) and p.suffix == ".js" and p.exists():
                    res_wt.append(p)
            if res_wt:
                return sorted(set(res_wt))
        except Exception:
            pass
        base = git_base()
        refs = []
        if base:
            refs.append(f"{base}..HEAD")
            refs.append("origin/main..HEAD")
        refs.extend(["HEAD~1..HEAD", "HEAD~2..HEAD", "HEAD~3..HEAD"])
        for ref in refs:
            try:
                out = subprocess.check_output(["git", "diff", "--name-only", ref], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
                try:
                    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
                    out += "\n" + untracked
                except Exception:
                    pass
                res = []
                for line in out.splitlines():
                    if not line.strip():
                        continue
                    p = ROOT / line.strip()
                    if str(p).startswith(str(WEB)) and p.suffix == ".js" and p.exists():
                        res.append(p)
                total_js = len(list(WEB.rglob("*.js"))) if WEB.exists() else 1
                if len(res) > total_js * 0.5:
                    continue
                if ref.startswith("HEAD~"):
                    return sorted(set(res))
                if len(res) == 0:
                    return []
                return sorted(set(res))
            except Exception:
                continue
        return []
    return sorted(WEB.rglob("*.js")) if WEB.exists() else []

def get_overrides(node: ast.AST, lines: List[str]) -> Dict[str, tuple]:
    ov = {}
    try:
        ln = getattr(node, "lineno", 1)
        for i in range(max(0, ln - 3), min(len(lines), ln + 1)):
            m = OVERRIDE_RE.search(lines[i])
            if m:
                ov[m.group("m").lower()] = (m.group("v"), m.group("r").strip())
    except Exception:
        pass
    return ov

def count_params(fn, in_cls=False) -> int:
    a = fn.args
    c = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
    if in_cls and a.args and a.args[0].arg in ("self", "cls"):
        c = max(0, c - 1)
    return c

def nesting_depth(node, d=0, mx=0) -> int:
    nd = d + 1 if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With)) else d
    mx = max(mx, nd)
    for ch in ast.iter_child_nodes(node):
        mx = nesting_depth(ch, nd, mx)
    return mx

def cc_simple(node) -> int:
    cc = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With)):
            cc += 1
        elif isinstance(n, ast.BoolOp) and isinstance(n.op, (ast.And, ast.Or)):
            cc += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            cc += len(n.ifs)
        elif isinstance(n, (ast.IfExp, ast.Assert)):
            cc += 1
    return cc

def try_radon(p: Path) -> Optional[Dict[str, int]]:
    try:
        out = subprocess.check_output(["python", "-m", "radon", "cc", "-s", "-j", str(p)], text=True, stderr=subprocess.DEVNULL, timeout=10)
        data = json.loads(out)
        res = {}
        for _, ents in data.items():
            for e in ents:
                res[e["name"]] = e["complexity"]
        return res
    except Exception:
        return None

def try_cog(p: Path) -> Optional[Dict[str, int]]:
    try:
        from cognitive_complexity.api import get_cognitive_complexity
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
        res = {}
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    res[n.name] = get_cognitive_complexity(n)
                except Exception:
                    pass
        return res
    except Exception:
        return None

def check_py_file(fp: Path) -> tuple[List[Dict], Dict]:
    breaches = []
    cur_max = {"max_func_loc": 0, "max_class_loc": 0, "max_methods": 0, "max_cc": 0, "max_cog": 0, "max_nest": 0, "max_params": 0, "file_lines": 0, "func_count": 0}
    try:
        src = fp.read_text(encoding="utf-8")
    except Exception as e:
        return [{"file": str(fp), "fail": True, "message": f"read fail {e}"}], cur_max
    lines = src.splitlines()
    cur_max["file_lines"] = len(lines)
    try:
        tree = ast.parse(src, filename=str(fp))
    except SyntaxError as e:
        return [{"file": str(fp), "fail": True, "message": f"syntax {e}"}], cur_max
    radon = try_radon(fp)
    cogmap = try_cog(fp)

    def walk(node, stack=None):
        if stack is None:
            stack = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            cur_max["func_count"] += 1
            if re.search(r"_part\d+$", name):
                breaches.append({"file": str(fp.relative_to(ROOT)), "lineno": node.lineno, "metric": "anti-gaming", "fail": True, "message": f"{name} gaming split"})
            loc = (getattr(node, "end_lineno", None) or node.lineno) - node.lineno + 1
            cur_max["max_func_loc"] = max(cur_max["max_func_loc"], loc)
            ov = get_overrides(node, lines)
            if loc > LIMITS["func_loc"] and "loc" not in ov:
                breaches.append({"file": str(fp.relative_to(ROOT)), "lineno": node.lineno, "metric": "loc", "value": loc, "limit": LIMITS["func_loc"], "fail": True, "message": f"{name} LOC {loc} > {LIMITS['func_loc']}"})
            in_cls = any(isinstance(x, ast.ClassDef) for x in stack)
            pc = count_params(node, in_cls)
            cur_max["max_params"] = max(cur_max["max_params"], pc)
            if pc > LIMITS["params"] and "params" not in ov:
                breaches.append({"file": str(fp.relative_to(ROOT)), "lineno": node.lineno, "metric": "params", "value": pc, "fail": True, "message": f"{name} params {pc} > {LIMITS['params']}"})
            cc = radon[name] if radon and name in radon else cc_simple(node)
            cur_max["max_cc"] = max(cur_max["max_cc"], cc)
            if cc > LIMITS["cc"] and "cc" not in ov:
                breaches.append({"file": str(fp.relative_to(ROOT)), "lineno": node.lineno, "metric": "cc", "value": cc, "fail": True, "message": f"{name} CC {cc} > {LIMITS['cc']}"})
            cg = cogmap[name] if cogmap and name in cogmap else None
            if cg is not None:
                cur_max["max_cog"] = max(cur_max["max_cog"], cg)
                if cg > LIMITS["cognitive"] and "cognitive" not in ov:
                    breaches.append({"file": str(fp.relative_to(ROOT)), "lineno": node.lineno, "metric": "cognitive", "value": cg, "fail": True, "message": f"{name} cog {cg} > {LIMITS['cognitive']}"})
            nd = nesting_depth(node)
            cur_max["max_nest"] = max(cur_max["max_nest"], nd)
            if nd > LIMITS["nesting"] and "nesting" not in ov:
                breaches.append({"file": str(fp.relative_to(ROOT)), "lineno": node.lineno, "metric": "nesting", "value": nd, "fail": True, "message": f"{name} nesting {nd} > {LIMITS['nesting']}"})
        if isinstance(node, ast.ClassDef):
            loc = (getattr(node, "end_lineno", None) or node.lineno) - node.lineno + 1
            cur_max["max_class_loc"] = max(cur_max["max_class_loc"], loc)
            ov = get_overrides(node, lines)
            if loc > LIMITS["class_loc"] and "class-loc" not in ov and "loc" not in ov:
                breaches.append({"file": str(fp.relative_to(ROOT)), "lineno": node.lineno, "metric": "class-loc", "value": loc, "fail": True, "message": f"Class {node.name} LOC {loc} > {LIMITS['class_loc']}"})
            mcount = len([n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])
            cur_max["max_methods"] = max(cur_max["max_methods"], mcount)
            if mcount > LIMITS["methods"] and "methods" not in ov:
                breaches.append({"file": str(fp.relative_to(ROOT)), "lineno": node.lineno, "metric": "methods", "value": mcount, "fail": True, "message": f"Class {node.name} methods {mcount} > {LIMITS['methods']}"})
        for ch in ast.iter_child_nodes(node):
            walk(ch, stack + [node])

    walk(tree)
    return breaches, cur_max

def check_js_via_node(files: List[Path], baseline: Dict = None, allow_legacy=False, changed_mode=False) -> List[Dict]:
    breaches = []
    # In changed mode, if no files, skip JS gate entirely (no js changed)
    if changed_mode and files is not None and len(files) == 0:
        return []
    tool = ROOT / "tools" / "js_metrics.js"
    if not tool.exists():
        return [{"file": "tools/js_metrics.js", "fail": False, "message": "js_metrics.js missing, run npm ci"}]
    try:
        out = subprocess.check_output(["node", str(tool), str(WEB), "--json"], text=True, timeout=20)
        data = json.loads(out)
        # Build per-file current maxima for ratchet
        per_file_cur = {}
        for e in data:
            if e.get("isFile"):
                per_file_cur.setdefault(e["file"], {"file_lines": e.get("fileLines", 0), "max_func_loc": 0, "max_cc": 0, "max_nest": 0, "max_params": 0, "func_count": 0})
                per_file_cur[e["file"]]["file_lines"] = e.get("fileLines", 0)
            else:
                if e.get("error"):
                    continue
                f = e.get("file", "")
                per_file_cur.setdefault(f, {"file_lines": 0, "max_func_loc": 0, "max_cc": 0, "max_nest": 0, "max_params": 0, "func_count": 0})
                per_file_cur[f]["max_func_loc"] = max(per_file_cur[f]["max_func_loc"], e.get("loc", 0))
                per_file_cur[f]["max_cc"] = max(per_file_cur[f]["max_cc"], e.get("cc", 0))
                per_file_cur[f]["max_nest"] = max(per_file_cur[f]["max_nest"], e.get("depth", 0))
                per_file_cur[f]["max_params"] = max(per_file_cur[f]["max_params"], e.get("params", 0))
                per_file_cur[f]["func_count"] += 1
        # Ratchet for JS: fail if current > baseline (including func_count growth)
        if baseline is not None:
            for f, cur in per_file_cur.items():
                base = baseline.get(f)
                if not base:
                    continue
                for k in ["max_func_loc", "max_cc", "max_nest", "max_params", "file_lines", "func_count"]:
                    cb = cur.get(k, 0)
                    bb = base.get(k, 0)
                    if cb > bb:
                        breaches.append({"file": f, "metric": f"ratchet-js-{k}", "value": cb, "baseline": bb, "fail": True, "message": f"RATCHET JS {f} {k} grew {bb}→{cb}"})
        # Now check actual breaches, but filter by requested files if changed mode
        target_set = set(str(x.relative_to(ROOT)) if x.is_relative_to(ROOT) else str(x) for x in files) if files else None
        for e in data:
            if e.get("isFile"):
                if e.get("fileLines", 0) > 500:
                    # file size warn, not fail, unless new growth already flagged
                    breaches.append({"file": e["file"], "metric": "js-file-loc", "value": e["fileLines"], "fail": False, "message": f"JS file {e['file']} lines {e['fileLines']} > 500 ideal 150-300"})
                continue
            if e.get("error"):
                continue
            f = e.get("file", "")
            if target_set is not None and len(target_set) > 0:
                # If changed mode and file not in changed set, skip unless it's ratchet (already added)
                if f not in target_set and not any(f in str(t) or str(t) in f for t in target_set):
                    continue
            loc = e.get("loc", 0)
            params = e.get("params", 0)
            depth = e.get("depth", 0)
            cc = e.get("cc", 0)
            name = e.get("name", "anon")
            line = e.get("line", 0)
            items = []
            if loc > LIMITS["func_loc"]:
                items.append({"file": f, "lineno": line, "metric": "js-loc", "value": loc, "fail": True, "message": f"JS {name} LOC {loc} > {LIMITS['func_loc']} at {f}:{line}"})
            if params > LIMITS["params"]:
                items.append({"file": f, "lineno": line, "metric": "js-params", "value": params, "fail": True, "message": f"JS {name} params {params} > {LIMITS['params']}"})
            if depth > LIMITS["nesting"]:
                items.append({"file": f, "lineno": line, "metric": "js-nesting", "value": depth, "fail": True, "message": f"JS {name} nesting {depth} > {LIMITS['nesting']}"})
            if cc > LIMITS["cc"]:
                items.append({"file": f, "lineno": line, "metric": "js-cc", "value": cc, "fail": True, "message": f"JS {name} CC {cc} > {LIMITS['cc']}"})
            # Apply legacy downgrade if allow_legacy and file in baseline and not growth
            for it in items:
                if allow_legacy and baseline and f in baseline:
                    # Check if this specific metric is within baseline max
                    base = baseline[f]
                    kmap = {"js-loc": "max_func_loc", "js-cc": "max_cc", "js-nesting": "max_nest", "js-params": "max_params"}
                    bk = kmap.get(it["metric"])
                    if bk and it["value"] <= base.get(bk, 9999):
                        it["fail"] = False
                        it["message"] = f"[LEGACY JS] {it['message']} baseline {base.get(bk)}"
                breaches.append(it)
    except Exception as ex:
        breaches.append({"file": "js", "fail": False, "message": f"JS gate failed to run: {ex}"})
    return breaches

def load_baseline(path: Path) -> Dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def check_coverage(allow_legacy=False, baseline: Dict = None) -> List[Dict]:
    cov = ROOT / "coverage.json"
    if not cov.exists():
        return [{"file": "coverage.json", "metric": "missing", "fail": False, "message": "coverage.json missing — run coverage"}]
    try:
        data = json.loads(cov.read_text(encoding="utf-8"))
        tot = data.get("totals", {})
        line_pct = tot.get("percent_covered", 0)
        cb = tot.get("covered_branches", 0)
        nb = tot.get("num_branches", 0)
        bp = (cb / nb * 100) if nb else 0
        br = []
        if line_pct < 80:
            fail = not allow_legacy
            msg = f"Line {line_pct:.1f}% <80%"
            if allow_legacy:
                msg = f"[LEGACY] {msg} baseline 41%"
            br.append({"file": "coverage.json", "metric": "line", "value": line_pct, "fail": fail, "message": msg})
        if nb and bp < 75:
            fail = not allow_legacy
            msg = f"Branch {bp:.1f}% <75%"
            if allow_legacy:
                msg = f"[LEGACY] {msg} baseline 32%"
            br.append({"file": "coverage.json", "metric": "branch", "value": bp, "fail": fail, "message": msg})
        # Per-file coverage ratchet R0.3: fail if current < baseline
        if baseline:
            files_cov = data.get("files", {})
            for fp, fdata in files_cov.items():
                rel = fp
                if "app/" in fp:
                    rel = fp[fp.find("app/"):]
                base = baseline.get(rel)
                if not base or "coverage" not in base:
                    continue
                cur_cov = fdata.get("summary", {}).get("percent_covered", 0)
                base_cov = base.get("coverage", 0)
                # Allow small float tolerance, but fail if drop >0.5%
                if cur_cov + 0.5 < base_cov:
                    br.append({"file": rel, "metric": "ratchet-coverage", "value": cur_cov, "baseline": base_cov, "fail": True, "message": f"RATCHET {rel} coverage dropped {base_cov:.1f}%→{cur_cov:.1f}% (even in baseline, growth fails)"})
        return br
    except Exception as e:
        return [{"file": "coverage.json", "fail": False, "message": f"parse fail {e}"}]

def ratchet_check(fp: Path, cur_max: Dict, baseline: Dict, allow_legacy: bool) -> List[Dict]:
    rel = str(fp.relative_to(ROOT))
    base = baseline.get(rel)
    if not base:
        return []
    br = []
    for k in ["max_func_loc", "max_class_loc", "max_methods", "max_cc", "max_cog", "max_nest", "max_params", "file_lines", "func_count"]:
        cur = cur_max.get(k, 0)
        b = base.get(k, 0)
        if cur > b:
            br.append({"file": rel, "metric": f"ratchet-{k}", "value": cur, "baseline": b, "fail": True, "message": f"RATCHET {rel} {k} grew {b}→{cur} (even in baseline, growth fails)"})
    return br

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--changed", action="store_true")
    ap.add_argument("--allow-legacy", action="store_true")
    ap.add_argument("--baseline", default="tools/quality_baseline.json")
    ap.add_argument("--js", action="store_true", help="include JS gate")
    ap.add_argument("--no-js", action="store_true", help="skip JS gate")
    args = ap.parse_args()

    baseline = load_baseline(Path(args.baseline))
    py_files = find_py_files(changed=args.changed)
    js_files = [] if args.no_js else find_js_files(changed=args.changed)

    all_br, cur_map = [], {}
    for fp in py_files:
        br, cm = check_py_file(fp)
        cur_map[str(fp.relative_to(ROOT))] = cm
        # Ratchet check before legacy downgrade
        rc = ratchet_check(fp, cm, baseline, args.allow_legacy)
        all_br.extend(rc)
        if args.allow_legacy:
            rel = str(fp.relative_to(ROOT))
            if rel in baseline:
                # Downgrade only if not growth (growth already added as fail)
                # If breach metric still within baseline, downgrade to warn
                filtered = []
                for b in br:
                    # Check if this breach is due to legacy value not growth
                    # We already have growth fails in rc, so downgrade rest
                    if b.get("metric") == "anti-gaming":
                        filtered.append(b)
                    else:
                        b["fail"] = False
                        b["message"] = f"[LEGACY] {b['message']} baseline {baseline[rel].get('max_func_loc')}/{baseline[rel].get('max_class_loc')}"
                        filtered.append(b)
                br = filtered
        all_br.extend(br)

    # JS gate R0.2
    if not args.no_js:
        if args.changed and len(js_files) == 0:
            js_br = []
        else:
            js_target = js_files if args.changed else sorted(WEB.rglob("*.js"))
            js_br = check_js_via_node(js_target, baseline=baseline, allow_legacy=args.allow_legacy, changed_mode=args.changed)
        all_br.extend(js_br)

    cov_br = check_coverage(allow_legacy=args.allow_legacy, baseline=baseline)
    all_br.extend(cov_br)

    fails = [b for b in all_br if b.get("fail")]
    warns = [b for b in all_br if not b.get("fail")]

    if args.json:
        print(json.dumps({"breaches": all_br, "fails": fails, "warns": warns, "files_checked": len(py_files), "js_files": len(js_files), "current_max": cur_map}, indent=2))
    else:
        print(f"Checked {len(py_files)} py files, {len(js_files)} js files")
        print(f"Fails {len(fails)} Warns {len(warns)}")
        if fails:
            print("\n=== FAILS ===")
            for b in fails:
                print(f"{b.get('file')}:{b.get('lineno','')} [{b.get('metric')}] {b.get('message')}")
        if warns:
            print("\n=== WARNS ===")
            for b in warns[:50]:
                print(f"{b.get('file')} [{b.get('metric','')}] {b.get('message')}")
            if len(warns) > 50:
                print(f"... {len(warns)-50} more warns")
        if not fails:
            print("\n✅ PASSED")
        else:
            print("\n❌ FAILED — fix fails before push (RULE 16)")
            print("Remediation order RULE 19: nesting→CC→cognitive→size")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
