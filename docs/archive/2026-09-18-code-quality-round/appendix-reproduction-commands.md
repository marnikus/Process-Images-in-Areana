# Appendix — reproduction commands

Everything in this folder was produced with the commands below on snapshot
`67fae78`. The ad-hoc scripts live in `/tmp` during measurement; **Round 0 step
R0.1 folds them into `tools/metrics_report.py`** so the next round reproduces the
numbers with one command.

Working environment used here (outside the repo tree is fine; `.venv/` is
git-ignored):

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt radon vulture coverage cognitive-complexity
npm ci                      # only needed for the jsdom-based JS suites
```

## A.1 Gate (RULE 16) — the headline numbers

```bash
python tools/verify_quality.py --json > /tmp/gate.json
python - <<'EOF'
import json, collections
d = json.load(open('/tmp/gate.json'))
print("files_checked", d['files_checked'], "fails", len(d['fails']), "warns", len(d['warns']))
print(collections.Counter(b['metric'] for b in d['fails']))
rows = collections.defaultdict(collections.Counter)
for b in d['fails']:
    rows[b['file']][b['metric']] += 1
for f, c in sorted(rows.items(), key=lambda kv: -sum(kv[1].values())):
    print(sum(c.values()), f, dict(c))
EOF
```

Also run `python tools/verify_quality.py --changed --allow-legacy` — this is what
the pre-push hook runs, and it is where the *hole* described in §7 of the audit
is visible: every breach in a baseline-listed file is downgraded to a warning.

## A.2 Tests, coverage, branch coverage

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m coverage run --branch --source=app -m pytest tests -q
.venv/bin/python -m coverage json -o /tmp/coverage.json
.venv/bin/python - <<'EOF'
import json
d = json.load(open('/tmp/coverage.json')); t = d['totals']
print("line %:", round(t['percent_statements_covered'], 1), "branch %:",
      round(t['covered_branches']/t['num_branches']*100, 1), "combined %:", round(t['percent_covered'], 1))
for f, i in sorted(d['files'].items(), key=lambda kv: kv[1]['summary']['percent_covered'])[:15]:
    print(f"{i['summary']['percent_covered']:5.1f}%  {len(i['missing_lines']):5d} missing  {f}")
EOF
npm run test:js        # 99 Node tests; 1 needs jsdom (npm ci)
```

## A.3 Complexity: radon CC + MI

```bash
.venv/bin/python -m radon cc -s -n D app          # only D+ offenders
.venv/bin/python -m radon cc -s -a app | tail -3  # block count + average
.venv/bin/python -m radon mi -s app | sort -t'(' -k2 | head -8
```

## A.4 Cognitive complexity, nesting, params, function size distribution

```bash
.venv/bin/python - <<'EOF'
import ast, os, statistics
from cognitive_complexity.api import get_cognitive_complexity

def nesting(n, d=0, mx=0):
    nd = d + 1 if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With)) else d
    mx = max(mx, nd)
    for c in ast.iter_child_nodes(n):
        mx = nesting(c, nd, mx)
    return mx

locs, cog_over, nest_over, par_over = [], [], [], []
for dp, _, fns in os.walk('app'):
    if '__pycache__' in dp:
        continue
    for fn in (f for f in fns if f.endswith('.py')):
        p = os.path.join(dp, fn)
        tree = ast.parse(open(p, encoding='utf-8').read())
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            loc = n.end_lineno - n.lineno + 1
            locs.append(loc)
            if get_cognitive_complexity(n) > 15:
                cog_over.append((get_cognitive_complexity(n), loc, p, n.lineno, n.name))
            if nesting(n) > 4:
                nest_over.append((nesting(n), p, n.lineno, n.name))
            a = n.args
            pc = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
            if a.args and a.args[0].arg in ('self', 'cls'):
                pc = max(0, pc - 1)
            if pc > 4:
                par_over.append((pc, p, n.lineno, n.name))
locs.sort()
print(f"functions {len(locs)} mean {statistics.mean(locs):.2f} median {statistics.median(locs)} "
      f"p95 {locs[int(.95*len(locs))]} max {locs[-1]}")
print("4-20 band", sum(1 for l in locs if 4 <= l <= 20), ">30", sum(1 for l in locs if l > 30))
print("cognitive>15", len(cog_over), sorted(cog_over, reverse=True)[:10])
print("nesting>4", len(nest_over), sorted(nest_over, reverse=True))
print("params>4", len(par_over), sorted(par_over, reverse=True))
EOF
```

## A.5 Files, classes, coverage per layer, MI summary

```bash
.venv/bin/python - <<'EOF'
import ast, os, json, statistics, subprocess, collections
cov = json.load(open('/tmp/coverage.json'))
files, classes = [], []
for dp, _, fns in os.walk('app'):
    if '__pycache__' in dp:
        continue
    for fn in (f for f in fns if f.endswith('.py')):
        p = os.path.join(dp, fn)
        src = open(p, encoding='utf-8').read()
        tree = ast.parse(src)
        f_ = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        files.append((p, len(src.splitlines()), len(f_)))
        for n in (x for x in ast.walk(tree) if isinstance(x, ast.ClassDef)):
            classes.append((n.end_lineno - n.lineno + 1,
                            len([x for x in n.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]), p, n.name))
print("files", len(files), "lines", sum(f[1] for f in files),
      ">300", sum(1 for f in files if f[1] > 300), ">500", sum(1 for f in files if f[1] > 500))
print("classes", len(classes), ">150", sum(1 for c in classes if c[0] > 150), ">300", sum(1 for c in classes if c[0] > 300))
print("top classes", sorted(classes, reverse=True)[:8])
pkg = collections.defaultdict(lambda: [0.0, 0])
for p, _, _ in files:
    s = cov['files'].get(p, {}).get('summary')
    if not s:
        continue
    k = '/'.join(p.split('/')[:2])
    pkg[k][0] += s['num_statements'] * s['percent_covered'] / 100
    pkg[k][1] += s['num_statements']
print({k: f"{v[0]/v[1]*100:.1f}%" for k, v in pkg.items()})
mi = subprocess.run(['.venv/bin/python', '-m', 'radon', 'mi', '-s', 'app'], capture_output=True, text=True).stdout
vals = sorted(float(l.split(' - ')[1].split('(')[1].split(')')[0]) for l in mi.splitlines() if ' - ' in l)
print("MI mean", round(statistics.mean(vals), 2), "min", vals[0], "<20", sum(1 for v in vals if v < 20))
EOF
```

## A.6 Dead-code detectors (three independent checks)

```bash
# 1) import graph: modules with zero app-importers and zero test-importers
.venv/bin/python - <<'EOF'
import os, re
mods = {}
for dp, _, fns in os.walk('app'):
    if '__pycache__' in dp:
        continue
    for fn in (f for f in fns if f.endswith('.py')):
        p = os.path.join(dp, fn)
        m = os.path.relpath(p, '.').replace('/', '.')[:-3].removesuffix('.__init__')
        mods[m] = p
pool = list(mods.values())
for base in ('tests', 'tools'):
    for dp, _, fns in os.walk(base):
        pool += [os.path.join(dp, f) for f in fns if f.endswith('.py')]
for m, p in sorted(mods.items()):
    if m.count('.') < 1:
        continue
    pat = re.compile(r'(from\s+\S*' + re.escape(m) + r'\s+import)|(import\s+' + re.escape(m) + r'\b)')
    hits = [q for q in pool if q != p and pat.search(open(q, encoding='utf-8', errors='ignore').read())]
    if not hits:
        print(f"{len(open(p, encoding='utf-8').read().splitlines()):5d} LOC  no importer: {m}")
EOF
# 2) symbol references
grep -rn "BrowserController\|JobRunner\|can_job_transition\|decide_ready" app tests tools | grep -v __pycache__
# 3) runtime: coverage of the suspect modules after the full suite
#    (0.0% in /tmp/coverage.json for controller.py and job_runner.py)
```

## A.7 Duplication

```bash
mkdir -p /tmp/jscpd && (cd /tmp/jscpd && npm install --silent jscpd)
npx --prefix /tmp/jscpd jscpd app tests --min-tokens 60 --reporters json --output /tmp/jscpd-out
python -c "import json; d=json.load(open('/tmp/jscpd-out/jscpd-report.json')); \
print(d['statistics']['total']); [print(c['lines'], c['firstFile']['name'], c['secondFile']['name']) \
for c in sorted(d['duplicates'], key=lambda x:-x['lines'])[:25]]"
```

## A.8 Unused code

```bash
.venv/bin/python -m vulture app --min-confidence 90   # 2 unused imports
.venv/bin/python -m vulture app --min-confidence 60   # 30 candidates for triage
```

## A.9 LCOM4 (methods sharing instance attributes → connected components)

```bash
.venv/bin/python - <<'EOF'
import ast, collections
for path, clsname in [('app/ui/bridge.py','Bridge'), ('app/browser/cdp_client.py','CDPClient'),
                      ('app/browser/cdp_arena.py','CDPArenaController'), ('app/services/watcher.py','WatcherService')]:
    tree = ast.parse(open(path, encoding='utf-8').read())
    cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == clsname][0]
    attrs = {}
    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            attrs[n.name] = {x.attr for x in ast.walk(n)
                             if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id == 'self'}
    names = list(attrs); parent = {n: n for n in names}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if attrs[names[i]] & attrs[names[j]]:
                ra, rb = find(names[i]), find(names[j])
                if ra != rb: parent[ra] = rb
    comps = collections.Counter(find(n) for n in names)
    print(f"{path}::{clsname} methods={len(names)} LCOM4={len(comps)} largest={sorted(comps.values(), reverse=True)[:5]}")
EOF
```

## A.10 Coupling (Ca / Ce / instability per layer)

```bash
.venv/bin/python - <<'EOF'
import ast, os, collections
edges = collections.Counter()
for dp, _, fns in os.walk('app'):
    if '__pycache__' in dp:
        continue
    for fn in (f for f in fns if f.endswith('.py')):
        p = os.path.join(dp, fn)
        mod = os.path.relpath(p, '.').replace('/', '.')[:-3]
        for n in ast.walk(ast.parse(open(p, encoding='utf-8').read())):
            if isinstance(n, ast.ImportFrom) and (n.module or '').startswith('app'):
                edges[('.'.join(mod.split('.')[:2]), '.'.join(n.module.split('.')[:2]))] += 1
            elif isinstance(n, ast.Import):
                for al in n.names:
                    if al.name.startswith('app'):
                        edges[('.'.join(mod.split('.')[:2]), '.'.join(al.name.split('.')[:2]))] += 1
ca, ce = collections.Counter(), collections.Counter()
for (a, b), n in edges.items():
    if a != b:
        ce[a] += n; ca[b] += n
for p in sorted(set(ca) | set(ce)):
    i = ce[p] / (ca[p] + ce[p]) if ca[p] + ce[p] else 0
    print(f"{p:22s} Ca={ca[p]:3d} Ce={ce[p]:3d} I={i:.2f}")
EOF
```

## A.11 JavaScript metrics (acorn)

```bash
mkdir -p /tmp/jsacorn && (cd /tmp/jsacorn && npm install --silent acorn acorn-walk)
# /tmp/jsacorn/metrics.mjs walks app/ui/web, measures every function
# (loc, params, nesting, rough CC incl. logical operators) and every file size:
node /tmp/jsacorn/metrics.mjs app/ui/web > /tmp/js_all.txt
node - <<'EOF'
const d = JSON.parse(require('fs').readFileSync('/tmp/js_metrics.json', 'utf8')).filter(r => !r.error);
const locs = d.map(r => r.loc).sort((a, b) => a - b); const n = locs.length;
console.log(`fn ${n} mean ${(locs.reduce((a,b)=>a+b,0)/n).toFixed(2)} median ${locs[n>>1]} max ${locs[n-1]}`);
console.log(`>30 LOC ${d.filter(r=>r.loc>30).length}  nesting>4 ${d.filter(r=>r.depth>4).length}  CC>10 ${d.filter(r=>r.cc>10).length}  params>4 ${d.filter(r=>r.params>4).length}`);
for (const r of d.filter(r => r.loc > 30).sort((a, b) => b.loc - a.loc).slice(0, 15))
  console.log(`${String(r.loc).padStart(4)} loc cc=${String(r.cc).padStart(3)} depth=${String(r.depth).padStart(2)} ${r.file}:${r.line} ${r.name}`);
EOF
```

## A.12 Technical-debt estimate (documented model, not a measurement)

```bash
.venv/bin/python - <<'EOF'
import json
d = json.load(open('/tmp/gate.json'))
W = {'class-loc': 0.5, 'methods': 5, 'loc': 0.5, 'cc': 8, 'nesting': 10, 'params': 5}
LIM = {'class-loc': 150, 'methods': 15, 'loc': 30, 'cc': 10, 'nesting': 4, 'params': 4}
debt = sum(max(0, (b['value'] - LIM[b['metric']])) * W[b['metric']]
           for b in d['fails'] if b['metric'] in LIM and isinstance(b['value'], (int, float)))
loc = 18929
print(f"remediation {debt:.0f} min = {debt/60:.1f} h; 30 min/LOC x {loc} LOC = {loc*30/60:.0f} h "
      f"-> tech-debt ratio {debt/(loc*30)*100:.2f}%")
EOF
```

## A.13 Churn and bug density

```bash
git rev-list --count HEAD          # = 1  -> churn not measurable (history squashed)
# bug density proxy: 15 documented defects (5 RC-* + 10 P-*) / 18,929 LOC = 0.79 per 1,000 LOC
# sources: docs/archive/2026-09-18-captcha-bot-failure-analysis/verification-and-problem-diagnostic.md
#          docs/archive/2026-09-18-captcha-solve-comparison-diagnostic/verification-and-problem-diagnostic.md
```
