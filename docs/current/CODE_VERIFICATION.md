# Code Verification Before Push — RULE 16 Enforcement

Per `AGENT_RULES.md` RULE 16, every production code change must pass quality gates before push. This document describes the verification workflow that must be run every time code is added.

## Why

Old App had detailed quality gates (LOC 30/150, params 4, methods 15, CC 10, cognitive 15, nesting 4, coverage 80%/75%) enforced via a gate script and pre-push hook. The Arena app preserves the same thresholds (adapted) and the same pattern.

Adding code without verification leads to:
- Functions >30 LOC that hide complexity
- Classes >150 LOC / >15 methods that become unmaintainable
- CC >10, nesting >4 that make logic hard to test
- Coverage drops below 80%/75%
- Anti-gaming (foo_part1, **kwargs dodge, dummy helpers)
- Selector maps drifting from the live probes (RULE 21) / dead modules accumulating (RULE 16.4)

## What to run before every push

**One command runs all of it:** `bash tools/pre_push_check.sh` (the pre-push hook does this automatically). Manual steps, in order:

### 1. Syntax check (whole production tree)
```bash
find app tools -name "*.py" -print0 | xargs -0 python -m py_compile
```

### 2. Quality gate — changed files only (legacy allowed)
```bash
python tools/verify_quality.py --changed --allow-legacy
```
- Checks files changed vs `origin/main` (git diff; falls back to all files when no merge base)
- Legacy files in `tools/quality_baseline.json` are allowed to exceed limits if not increased (grandfathered per RATCHET pattern)
- Fails on: new function LOC >30, class LOC >150, params >4, methods >15, CC >10, cognitive >15, nesting >4, anti-gaming (`_part1` split, `**kwargs` dodge)
- Full review of all files: `python tools/verify_quality.py`

### 3. RULE 21 selector sync — site_adapter must match the live probes
```bash
python tools/generate_selectors.py            # --check mode
```
- Extracts every live selector chain (cdp_arena probes, output_probes, new_chat, cdp_client, action-block defaults, captcha_js) and compares with the generated `SELECTORS` map in `app/browser/site_adapter.py`
- Fails on any drift. Fix: edit the probe, then `python tools/generate_selectors.py --write`

### 4. Dead-code closure — no new production-dead modules (RULE 16.4)
```bash
python tools/import_graph.py --dead
```
- AST import graph, production closure from `app.main`. Fails per new dead module
- `doc-kept` lines are the documented test-only modules (SYSTEM_OF_RECORD §8) — expected, not fails

### 5. Tests
```bash
python -m pytest tests -q
```

### 6. Coverage — report only
```bash
QT_QPA_PLATFORM=offscreen python -m coverage run --branch --source=app -m pytest tests -q
python -m coverage json -o coverage.json && python -m coverage report | tail -1
```
- **Report-only by design (2026-09-19):** the repo-wide coverage gap (42.7% line vs 80%/75%) is pre-existing and tracked in `docs/archive/2026-09-19-dead-code-quality-batch/improvements-2026-09-19.md`; `coverage` is also not in `requirements.txt`. The full gate still reports the gap; new files must still aim at the thresholds.

## Git hook — automatic enforcement

`.git/hooks/pre-push` runs `tools/pre_push_check.sh` automatically on `git push` (all steps above). The script resolves the interpreter itself (`$PY` = `.venv/bin/python` when present) — the hook environment has no PATH customisation.

- If the gate fails, the push is blocked.
- Bypass only with `git push --no-verify` for an explicit reason, after running verification manually (not recommended).
- Reinstall the hook:
```bash
bash tools/install_hooks.sh
```

## Override format (when a constraint forces a breach)

If a breach is unavoidable due to a real constraint (Qt slot signature, wire format, generated JS literal), add an override comment on the line above or the same line:

```python
# quality-override: cc=12 reason=Baseline capture must check 6 selectors + security dialog + sign-in, cannot reduce branches without deleting real decision
```

- Format strict: `quality-override: <metric>=<value> reason=<≥20 chars>`
- metric ∈ `loc, class-loc, params, methods, cc, cognitive, nesting, coverage, vulture, dup`
- Reason must name the constraint, not "faster to ship"
- One override per metric per symbol; a stale override must be deleted

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
| `tools/generate_selectors.py` | RULE 21 selector generator: extracts live probe chains → generated map in `site_adapter.py`; `--check` drift gate, `--write` regenerate, `--report` tiers, `--dump` debug |
| `tools/import_graph.py` | AST import graph; `--dead` = production-closure dead-module gate (RULE 16.4) |
| `tools/pre_push_check.sh` | Combined check: syntax (whole tree) + quality gate changed + selector sync + dead modules + tests + coverage report |
| `tools/install_hooks.sh` | Installs `.git/hooks/pre-push` → pre_push_check.sh |
| `docs/current/AGENT_RULES.md` | Detailed rules, thresholds, anti-gaming, override format |
| `docs/current/CODE_VERIFICATION.md` | This file — verification workflow |

## CI equivalent (if added later)

Same as the pre-push hook: run `bash tools/pre_push_check.sh` and fail on non-zero exit.

## Quick checklist for agent workflow (RULE 16 §16.6 adapted)

1. Read `current/SYSTEM_OF_RECORD.md` + `current/AGENT_RULES.md` rules 1–15 + RULE 18 size ideals
2. Research saved HTML in `research/` + `selector_map.md` + `current/DOM_SELECTORS.md`
3. Design in `archive/<date>-<topic>/` if complexity moves across files — record radon numbers, target numbers, dishonest reductions rejected
4. Tests first (RULE 8)
5. **Measure**: `python tools/verify_quality.py --changed --allow-legacy` — any new function fail → stop and redesign in order RULE 19
6. **Run**: `bash tools/pre_push_check.sh` — must pass before `git push`
7. Update current docs in the same change (RULE 17)

---

*Last updated: 2026-09-19 — synced with Batch B: whole-tree syntax step, selector-sync + dead-module gates, coverage report-only (pre-existing gap), venv interpreter resolution. Prior: 2026-09-15 mandatory verification workflow from Old App's rule16_gate.py.*
