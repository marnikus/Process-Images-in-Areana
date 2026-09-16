# Code Verification Before Push — RULE 16 Enforcement

Per `AGENT_RULES.md` RULE 16, every production code change must pass quality gates before push. This document describes the verification workflow that must be run every time code is added.

## Why

Old App had detailed quality gates (LOC 30/150, params 4, methods 15, CC 10, cognitive 15, nesting 4, coverage 80%/75%) enforced via `tools/metrics/rule16_gate.py` and pre-commit hook. New Arena app preserves same thresholds (adapted) and same pattern.

Adding code without verification leads to:
- Functions >30 LOC that hide complexity
- Classes >150 LOC / >15 methods that become unmaintainable
- CC >10, nesting >4 that make logic hard to test
- Coverage drops below 80%/75%
- Anti-gaming (foo_part1, **kwargs dodge, dummy helpers)

## What to run before every push

### 1. Syntax check
```bash
python -m py_compile app/browser/dom_highlight.py app/browser/probe_requests.py app/browser/visual_click.py app/core/action_blocks.py app/ui/bridge.py app/browser/cdp_arena.py app/core/layout_service.py
```

### 2. Quality gate — changed files only (legacy allowed)
```bash
python tools/verify_quality.py --changed --allow-legacy
```
- Checks only files changed vs `origin/main` (git diff)
- Legacy files in `tools/quality_baseline.json` are allowed to exceed limits if not increased (grandfathered per RATCHET pattern from Old App)
- Fails on:
  - New function LOC >30, class LOC >150, params >4, methods >15
  - CC >10, cognitive >15, nesting >4 on new/edited functions
  - Anti-gaming: `_part1` split, `**kwargs` dodge

### 3. Full quality gate (all app files) — for review
```bash
python tools/verify_quality.py
```
- Reports all fails/warns, including legacy. Use to see overall health.
- Legacy breaches are reported but allowed in `--allow-legacy` mode.

### 4. Tests
```bash
python -m pytest tests -q
```

### 5. Coverage
```bash
QT_QPA_PLATFORM=offscreen python -m coverage run --branch --source=app -m pytest tests -q
python -m coverage json -o coverage.json
python tools/verify_quality.py --json | python -c "import json,sys; data=json.load(sys.stdin); fails=[b for b in data['breaches'] if b.get('fail') and b.get('type')=='coverage']; sys.exit(1 if fails else 0)"
```
- Requires `coverage` pip package
- Thresholds: line ≥80%, branch ≥75%, never decrease vs baseline

### 6. Combined pre-push check (runs all above)
```bash
bash tools/pre_push_check.sh
```

## Git hook — automatic enforcement

A pre-push hook is installed at `.git/hooks/pre-push` that runs `tools/pre_push_check.sh` automatically on `git push`.

- If gate fails, push is blocked.
- Bypass only with `git push --no-verify` if you have explicit reason and have run verification manually (not recommended).
- Hook can be reinstalled via:
```bash
bash tools/install_hooks.sh
# or manually:
cp tools/pre_push_check.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

## Override format (when constraint forces breach)

If a breach is unavoidable due to real constraint (Qt slot signature, wire format, generated JS literal), add override comment on line above or same line:

```python
# quality-override: loc=35 reason=Qt slot signature requires 5 params, matches QWebChannel wire
def my_slot(self, a, b, c, d, e): ...

# quality-override: cc=12 reason=Baseline capture must check 6 selectors + security dialog + sign-in, cannot reduce branches without deleting real decision
```

- Format strict: `quality-override: <metric>=<value> reason=<≥20 chars>`
- metric ∈ `loc, class-loc, params, methods, cc, cognitive, nesting, coverage, vulture, dup`
- Reason must name constraint, not "faster to ship"
- One override per metric per symbol
- Override whose function now fits is stale and must be deleted

## Remediation order (RULE 19)

When code is over limit, fix in this order (size is symptom, others are cause):

1. **Nesting >4** → extract guard, early return, flatten
2. **CC >10** → split decision, not just code (no `foo_part1`)
3. **Cognitive >15** → name predicates, simplify boolean
4. **LOC >30** → extract helper with real responsibility name

Verify after every step: `python tools/verify_quality.py --changed` and `pytest`.

## Files

| File | Purpose |
|---|---|
| `tools/verify_quality.py` | RULE 16 gate implementation (AST-based LOC, params, methods, CC approx, nesting, anti-gaming, coverage) |
| `tools/quality_baseline.json` | Baseline for legacy files (max_func_loc, max_class_loc) — grandfathered, ratchet |
| `tools/pre_push_check.sh` | Combined check: syntax + quality gate changed + tests + coverage |
| `.git/hooks/pre-push` | Git hook that runs pre_push_check.sh on push |
| `docs/current/AGENT_RULES.md` | Detailed rules, thresholds, anti-gaming, override format |
| `docs/current/CODE_VERIFICATION.md` | This file — verification workflow |

## CI equivalent (if added later)

Same as pre-push hook, but in CI:
```bash
python tools/verify_quality.py --changed --allow-legacy --json > quality.json
# fail if any fail
```

## Quick checklist for agent workflow (RULE 16 §16.6 adapted)

From `AGENT_RULES.md`:

1. Read `current/SYSTEM_OF_RECORD.md` + `current/AGENT_RULES.md` rules 1-15 + RULE 18 size ideals
2. Research saved HTML in `research/` + `selector_map.md` + `current/DOM_SELECTORS.md`
3. Design in `archive/<date>-<topic>/` if complexity moves across files — record radon numbers, target numbers, dishonest reductions rejected
4. Tests first (RULE 8)
5. **Measure**: `python tools/verify_quality.py --changed --allow-legacy` — any new function fail → stop and redesign in order RULE 19
6. **Run**: `bash tools/pre_push_check.sh` — must pass before `git push`
7. Update current docs in same change (RULE 17)

---

*Last updated: 2026-09-15 — added mandatory verification before push, based on Old App's rule16_gate.py and AGENT_RULES.md detailed quality rules.*
