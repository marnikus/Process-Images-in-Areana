# Mutation Baseline — R0.6

**Decision:** `mutmut` vs `cosmic-ray`

| Criteria | mutmut | cosmic-ray | Verdict |
|---|---|---|---|
| Install | `pip install mutmut`, pure python, no docker | Needs docker or complex deps, slower | mutmut wins for local dev |
| Speed | Generates mutants in ms, runs via pytest, ~1 mutant/sec | Full AST, slower, needs worker pool | mutmut faster for fast lane |
| Config | `setup.cfg [mutmut] source_paths, runner` | `cosmic-ray` config file, more complex | mutmut simpler |
| Python 3.11 | Works (with warnings about deprecated config) | Partial, needs extra setup | mutmut better now |
| Reporting | `mutmut results`, `mutmut html` | `cr-report` | Both ok |
| Old App used | — | — | No precedent, choose simpler |

**Chosen:** **mutmut** for first round (fast, simple, local). cosmic-ray can be evaluated as nightly lane later if needed.

## How to run (scoped to correctness-critical)

```bash
# Install
pip install mutmut --break-system-packages

# Config for core (example)
cat > setup.cfg <<'CFG'
[mutmut]
source_paths=app/core
backup=False
runner=python -m pytest tests/test_naming.py tests/test_scanner.py tests/test_persistence.py -q
CFG

rm -rf mutants/
timeout 120 mutmut run
mutmut results
mutmut html

# For services
cat > setup.cfg <<'CFG'
[mutmut]
source_paths=app/services
backup=False
runner=python -m pytest tests/test_cooldown_service.py tests/test_watcher.py -q
CFG

rm -rf mutants/
timeout 180 mutmut run
mutmut results

# Cleanup
rm setup.cfg
rm -rf mutants/
```

**Note:** mutmut copies tests into `mutants/` and runs them; tests that import `tools` (e.g., `test_analyze_recording.py`) fail because `tools` not in `mutants/`. Exclude those tests via `-k "not test_analyze"` or set `PYTHONPATH`.

## Baseline score (to be measured)

Current status: **not measured** (no runner in repo before R0.6) — same as audit gap.

**Target:** ≥70% mutation score on scoped modules `app/core/**` + `app/services/**` + `app/browser/cdp*` (correctness-critical).

Old App baseline: 99.4% on covered modules, line 92.64% branch 88.03% — treat 70% as floor for first round, not goal.

**First measurement (placeholder, to be updated after full run):**

| Module | Mutants | Killed | Survived | Score | Notes |
|---|---|---|---|---|---|
| `app/core/naming.py` | ~20 | TBD | TBD | TBD | Small, should be ≥90% |
| `app/core/scanner.py` | ~30 | TBD | TBD | TBD | Predicate table will improve |
| `app/core/persistence.py` | ~40 | TBD | TBD | TBD | Needs negative matrix |
| `app/services/cooldown_service.py` | ~100 | TBD | TBD | TBD | Largest service file, 88.9% line cov |
| `app/services/watcher.py` | ~50 | TBD | TBD | TBD | Hotspot C1 |
| **Total core+services** | **~500** | **TBD** | **TBD** | **TBD** | Record after Areas A/B/C |

**Next steps:**

1. Run mutmut on `app/core/**` first (fast, ~12 files, ~200 mutants) → record score
2. Triage survivors into: (a) missing assertion, (b) equivalent mutant, (c) dead code to delete
3. Run on `app/services/**` (slower, ~17 files) → record
4. Store score in `metrics-report-2026-09-2X.md` with Before→After
5. Add nightly lane `tools/mutation_check.sh` (not on every push, too slow)

**Why not run on every push:** Mutation run time on big tree is minutes-hours. Scope to critical modules and run as nightly/manual lane, not on every push — same as Old App.

## Files

| File | Purpose |
|---|---|
| `tools/mutation_baseline.md` | This file: decision + baseline + how to run |
| `setup.cfg` (generated, git-ignored) | mutmut config, not committed |
| `mutants/` (generated, git-ignored) | mutmut working dir, not committed |

*Last updated: 2026-09-19 — R0.6 decision mutmut, baseline placeholder, instructions for core/services.*
