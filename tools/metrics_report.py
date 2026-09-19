#!/usr/bin/env python3
"""
R0.1 — One command reproducing metrics-baseline-2026-09-18.md ±1%
Usage: .venv/bin/python tools/metrics_report.py [--json] [--out /tmp/report.json]
"""
from __future__ import annotations
import ast, json, statistics, subprocess, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
WEB = ROOT / "app" / "ui" / "web"

def find_py() -> list[Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in str(p))

def parse(p: Path):
    try:
        return ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None

def nest(node, d=0, mx=0) -> int:
    nd = d + 1 if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With)) else d
    mx = max(mx, nd)
    for c in ast.iter_child_nodes(node):
        mx = nest(c, nd, mx)
    return mx

def count_params(fn, in_cls=False) -> int:
    a = fn.args
    c = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
    if in_cls and a.args and a.args[0].arg in ("self", "cls"):
        c = max(0, c - 1)
    return c

def collect_py():
    locs, classes, files = [], [], []
    cog_over, nest_over, par_over = [], [], []
    cog_all = []
    try:
        from cognitive_complexity.api import get_cognitive_complexity as cog_fn
    except Exception:
        cog_fn = None
    for p in find_py():
        src = p.read_text(encoding="utf-8", errors="ignore")
        tree = parse(p)
        if not tree:
            continue
        files.append((str(p.relative_to(ROOT)), len(src.splitlines()), sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))))
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                cloc = (n.end_lineno or n.lineno) - n.lineno + 1
                mcnt = len([x for x in n.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))])
                classes.append((cloc, mcnt, str(p.relative_to(ROOT)), n.name))
        # Walk with stack to track in_class for params
        def walk(node, stack=None):
            if stack is None:
                stack = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                locs.append(loc)
                in_cls = any(isinstance(x, ast.ClassDef) for x in stack)
                if cog_fn:
                    try:
                        cv = cog_fn(node)
                        cog_all.append(cv)
                        if cv > 15:
                            cog_over.append((cv, loc, str(p.relative_to(ROOT)), node.lineno, node.name))
                    except Exception:
                        pass
                nv = nest(node)
                if nv > 4:
                    nest_over.append((nv, str(p.relative_to(ROOT)), node.lineno, node.name))
                pc = count_params(node, in_cls)
                if pc > 4:
                    par_over.append((pc, str(p.relative_to(ROOT)), node.lineno, node.name))
            for ch in ast.iter_child_nodes(node):
                walk(ch, stack + [node])
        walk(tree)
    return locs, classes, files, cog_over, nest_over, par_over, cog_all

def radon_cc():
    try:
        out = subprocess.check_output([sys.executable, "-m", "radon", "cc", "-s", "-j", str(APP)], text=True, timeout=20)
        data = json.loads(out)
        blocks = []
        for _, ents in data.items():
            for e in ents:
                blocks.append((e["complexity"], e["lineno"], e["name"], e.get("endline", 0) - e["lineno"] + 1))
        blocks.sort(reverse=True)
        return blocks, [b for b in blocks if b[0] > 10]
    except Exception:
        return [], []

def radon_mi():
    try:
        out = subprocess.check_output([sys.executable, "-m", "radon", "mi", "-s", str(APP)], text=True, timeout=20)
        vals = []
        for line in out.splitlines():
            if " - " in line:
                try:
                    vals.append(float(line.split(" - ")[1].split("(")[1].split(")")[0]))
                except Exception:
                    pass
        return vals
    except Exception:
        return []

def coverage_data():
    cp = ROOT / "coverage.json"
    if not cp.exists():
        return None
    try:
        return json.loads(cp.read_text(encoding="utf-8"))
    except Exception:
        return None

def coupling():
    edges = Counter()
    for p in find_py():
        tree = parse(p)
        if not tree:
            continue
        mod = str(p.relative_to(ROOT)).replace("/", ".")[:-3]
        pkg = ".".join(mod.split(".")[:2])
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app"):
                edges[(pkg, ".".join(n.module.split(".")[:2]))] += 1
            elif isinstance(n, ast.Import):
                for al in n.names:
                    if al.name.startswith("app"):
                        edges[(pkg, ".".join(al.name.split(".")[:2]))] += 1
    ca, ce = Counter(), Counter()
    for (a, b), v in edges.items():
        if a != b:
            ce[a] += v
            ca[b] += v
    res = {}
    for pkg in set(ca) | set(ce):
        tot = ca[pkg] + ce[pkg]
        res[pkg] = (ca[pkg], ce[pkg], ce[pkg] / tot if tot else 0)
    return res

def lcom4():
    res = []
    targets = [("app/ui/bridge.py", "Bridge"), ("app/browser/cdp_client.py", "CDPClient"), ("app/browser/cdp_arena.py", "CDPArenaController"), ("app/services/watcher.py", "WatcherService")]
    for path, clsname in targets:
        fp = ROOT / path
        if not fp.exists():
            continue
        tree = parse(fp)
        if not tree:
            continue
        cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == clsname]
        if not cls:
            continue
        cls = cls[0]
        attrs = {}
        for n in cls.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                attrs[n.name] = {x.attr for x in ast.walk(n) if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id == "self"}
        names = list(attrs)
        parent = {n: n for n in names}
        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if attrs[names[i]] & attrs[names[j]]:
                    ra, rb = find(names[i]), find(names[j])
                    if ra != rb:
                        parent[ra] = rb
        comps = Counter(find(n) for n in names)
        res.append((path, clsname, len(names), len(comps), sorted(comps.values(), reverse=True)[:3]))
    return res

def vulture_metrics():
    def run_vul(conf):
        try:
            out = subprocess.check_output([sys.executable, "-m", "vulture", "app", "tools/vulture_whitelist.py", "--min-confidence", str(conf)], text=True, timeout=10, stderr=subprocess.STDOUT)
            return out
        except subprocess.CalledProcessError as e:
            # vulture exits 3 when finds dead code, still has output
            return e.output
        except Exception:
            return ""
    out90 = run_vul(90)
    out60 = run_vul(60)
    l90 = [l for l in out90.splitlines() if l.strip()]
    l60 = [l for l in out60.splitlines() if l.strip()]
    return {"90": len(l90), "60": len(l60), "sample90": l90[:5]}

def jscpd_metrics():
    try:
        out_dir = Path("/tmp/jscpd-out")
        out_dir.mkdir(exist_ok=True)
        subprocess.check_output(["npx", "jscpd", "app", "--min-tokens", "60", "--reporters", "json", "--output", str(out_dir), "--silent"], text=True, timeout=20)
        rep = out_dir / "jscpd-report.json"
        if rep.exists():
            d = json.loads(rep.read_text(encoding="utf-8"))
            total = d.get("statistics", {}).get("total", {})
            return {"pct": total.get("percentage", 0), "clones": len(d.get("duplicates", [])), "lines": total.get("duplicatedLines", 0)}
    except Exception:
        pass
    return {"pct": -1, "clones": -1}

def js_metrics():
    try:
        tool = ROOT / "tools" / "js_metrics.js"
        if tool.exists():
            out2 = subprocess.check_output(["node", str(tool), str(WEB), "--json"], text=True, timeout=10)
            data = json.loads(out2)
            funcs = [e for e in data if not e.get("isFile") and not e.get("error")]
            files = [e for e in data if e.get("isFile")]
            over30 = sum(1 for f in funcs if f.get("loc", 0) > 30)
            over4 = sum(1 for f in funcs if f.get("depth", 0) > 4)
            over_cc = sum(1 for f in funcs if f.get("cc", 0) > 10)
            return {"total_funcs": len(funcs), "total_files": len(files), "over30": over30, "nest_over4": over4, "cc_over10": over_cc, "raw": data[:3]}
    except Exception:
        pass
    return {}

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()

    locs, classes, files, cog_over, nest_over, par_over, cog_all = collect_py()
    cc_blocks, cc_over = radon_cc()
    mi_vals = radon_mi()
    cov = coverage_data()
    coup = coupling()
    lcom = lcom4()
    jsd = js_metrics()
    vul = vulture_metrics()
    jsc = jscpd_metrics()

    mean_loc = statistics.mean(locs) if locs else 0
    median_loc = statistics.median(locs) if locs else 0
    over30 = sum(1 for l in locs if l > 30)
    band = sum(1 for l in locs if 4 <= l <= 20)
    under4 = sum(1 for l in locs if l < 4)
    total_files = len(files)
    total_lines = sum(f[1] for f in files)
    over300 = sum(1 for f in files if f[1] > 300)
    over500 = sum(1 for f in files if f[1] > 500)
    ideal = sum(1 for f in files if 150 <= f[1] <= 300)
    c_over150 = sum(1 for c in classes if c[0] > 150)
    c_over300 = sum(1 for c in classes if c[0] > 300)

    report = {
        "python": {"files": total_files, "lines": total_lines, "funcs": len(locs), "mean": mean_loc, "median": median_loc, "max": max(locs) if locs else 0, "over30": over30, "band_4_20": band, "under4": under4, "classes": len(classes), "c_over150": c_over150, "c_over300": c_over300, "f_over300": over300, "f_over500": over500, "f_ideal": ideal, "cc_max": cc_blocks[0][0] if cc_blocks else 0, "cc_over10": len(cc_over), "cog_max": max(cog_all) if cog_all else 0, "cog_over15": len(cog_over), "nest_max": max([n[0] for n in nest_over]) if nest_over else 0, "nest_over4": len(nest_over), "params_over4": len(par_over)},
        "mi": {"mean": statistics.mean(mi_vals) if mi_vals else 0, "min": min(mi_vals) if mi_vals else 0, "under20": sum(1 for v in mi_vals if v < 20), "under40": sum(1 for v in mi_vals if v < 40)},
        "coupling": coup, "lcom4": lcom, "coverage": cov["totals"] if cov and "totals" in cov else None,
        "js": jsd, "vulture": vul, "jscpd": jsc,
    }

    if args.json or args.out:
        js = json.dumps(report, indent=2, default=str)
        if args.out:
            Path(args.out).write_text(js, encoding="utf-8")
        if args.json:
            print(js)
            return

    print(f"# Metrics Report — Files {total_files} Lines {total_lines} Funcs {len(locs)} Mean {mean_loc:.2f} Median {median_loc} Max {max(locs) if locs else 0}")
    print(f">30 {over30} 4-20 {band} <4 {under4} Over300 {over300} Over500 {over500} Ideal {ideal}")
    print(f"CC max {report['python']['cc_max']} over10 {len(cc_over)} Cog max {report['python']['cog_max']} over15 {len(cog_over)} Nest max {report['python']['nest_max']} over4 {len(nest_over)} Params>4 {len(par_over)}")
    print(f"MI mean {report['mi']['mean']:.2f} min {report['mi']['min']:.2f} <20 {report['mi']['under20']} <40 {report['mi']['under40']} Classes {len(classes)} >150 {c_over150} >300 {c_over300}")
    if cov and "totals" in cov:
        t = cov["totals"]
        bp = t["covered_branches"] / t["num_branches"] * 100 if t["num_branches"] else 0
        print(f"Coverage line {t['percent_covered']:.1f}% stmts {t['percent_statements_covered']:.1f}% branch {bp:.1f}%")
    print(f"Vulture @90 {vul.get('90')} @60 {vul.get('60')} Duplication {jsc.get('pct')}% {jsc.get('clones')} groups {jsc.get('lines')} lines")
    print(f"JS files {jsd.get('total_files',0)} funcs {jsd.get('total_funcs',0)} >30 {jsd.get('over30',0)} nest>4 {jsd.get('nest_over4',0)} CC>10 {jsd.get('cc_over10',0)}")
    print("Coupling:")
    for k, (ca, ce, inst) in sorted(coup.items()):
        print(f"  {k} Ca={ca} Ce={ce} I={inst:.2f}")
    print("LCOM4:")
    for r in lcom:
        print(f"  {r[0]}::{r[1]} methods={r[2]} LCOM4={r[3]}")

if __name__ == "__main__":
    main()
