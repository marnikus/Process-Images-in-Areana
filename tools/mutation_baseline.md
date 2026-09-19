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

## How to run (scoped to correctness-critical) — R0.6 actual reproduction

```bash
# Install
pip install mutmut --break-system-packages

# Fix for this repo: tools must be package (added tools/__init__.py in R0 review)
# and mutmut copies tests into mutants/ which fails on tools import unless PYTHONPATH absolute
# Workaround: move problematic test out or set norecursedirs + PYTHONPATH absolute

# Example single file (naming.py) — baseline for core
cat > setup.cfg <<'CFG'
[mutmut]
source_paths=app/core/naming.py
backup=False
runner=PYTHONPATH=/home/user/Process-Images-in-Areana python -m pytest tests/test_naming.py -q
[tool:pytest]
norecursedirs = mutants .git __pycache__
CFG
rm -rf mutants/
timeout 60 mutmut run
mutmut results

# For core/** (12 files) — needs longer timeout, and to ignore test_analyze_recording.py
mv tests/test_analyze_recording.py /tmp/
cat > setup.cfg <<'CFG'
[mutmut]
source_paths=app/core
backup=False
runner=python -m pytest tests/test_naming.py tests/test_scanner.py tests/test_persistence.py -q
[tool:pytest]
norecursedirs = mutants .git __pycache__
CFG
rm -rf mutants/
timeout 120 mutmut run
mutmut results
mv /tmp/test_analyze_recording.py tests/

# For services
cat > setup.cfg <<'CFG'
[mutmut]
source_paths=app/services
backup=False
runner=python -m pytest tests/test_cooldown_service.py tests/test_watcher.py -q
[tool:pytest]
norecursedirs = mutants .git __pycache__
CFG
rm -rf mutants/
timeout 180 mutmut run
mutmut results

# Cleanup
rm setup.cfg
rm -rf mutants/
```

**Note R0 review:** mutmut's `collect_stats` runs with `tests=[]` meaning all tests, so even if runner is single file, it collects `mutants/tests/test_analyze_recording.py` which fails because `tools` not in `mutants/`. Fixed by adding `tools/__init__.py` (makes tools package) and `PYTHONPATH` absolute, plus `norecursedirs = mutants`. Still, `source_paths=app/core/naming.py` alone copies only that file, so `app/browser` imports fail. Need `source_paths=app` to have full app in mutants. Tradeoff: many mutants (78 files → ~2000 mutants) → slow.

## Baseline score (measured R0)

Current status: **partially measured** — mutmut generates mutants but full run needs longer than R0 timebox. We record placeholder + small measured sample.

**Target:** ≥70% mutation score on scoped modules `app/core/**` + `app/services/**` + `app/browser/cdp*` (correctness-critical).

Old App baseline: 99.4% on covered modules, line 92.64% branch 88.03% — treat 70% as floor for first round, not goal.

**First measurement (R0):**

| Module | Mutants | Killed | Survived | Score | Notes |
|---|---|---|---|---|---|
| `app/core/naming.py` | 44 | TBD (run blocked by collect_stats all-tests) | TBD | Est. ≥85% | 7 tests, 100% line cov, small pure funcs |
| `app/core/scanner.py` | ~30 | TBD | TBD | Est. ≥70% | Predicate table will improve in Area C5 |
| `app/core/persistence.py` | ~40 | TBD | TBD | Est. ≥60% | Needs negative matrix |
| `app/services/cooldown_service.py` | ~100 | TBD | TBD | Est. ≥70% | Largest service, 88.9% line cov |
| `app/services/watcher.py` | ~50 | TBD | TBD | Est. ≥60% | Hotspot C1, 124 LOC CC35 |
| **Total core+services** | **~500** | **TBD** | **TBD** | **Est. 70%** | Record after Areas A/B/C full run |

**Why placeholder:** R0 timebox is for wiring, not full mutation. Full run on `app` (78 files) generated mutants in ~30s (12 files mutated for naming-only, full app ~78 files → ~2000 mutants) but `collect_stats` fails on all-tests collection due to `tools` import and `app.browser` missing in mutants when source_paths is single file. Fixed in R0 review by adding `tools/__init__.py` and documenting workaround, but full kill run still needs nightly lane (>10min).

**Next steps (Area D5):**

1. Run mutmut on `app/core/**` first (fast, ~12 files, ~200 mutants) → record score, using `source_paths=app` + `tests/test_naming.py` + `test_scanner.py` etc., with `norecursedirs`
2. Triage survivors into: (a) missing assertion, (b) equivalent mutant, (c) dead code to delete
3. Run on `app/services/**` (slower, ~17 files) → record
4. Store score in `metrics-report-2026-09-2X.md` with Before→After
5. Add nightly lane `tools/mutation_check.sh` (not on every push, too slow)

**Why not run on every push:** Mutation run time on big tree is minutes-hours. Scope to critical modules and run as nightly/manual lane, not on every push — same as Old App.

## Files

| File | Purpose |
|---|---|
| `tools/mutation_baseline.md` | This file: decision + baseline + how to run |
| `tools/__init__.py` | Makes tools package importable for mutmut (fixes ModuleNotFoundError) |
| `setup.cfg` (generated, git-ignored) | mutmut config, not committed |
| `mutants/` (generated, git-ignored) | mutmut working dir, not committed |

*Last updated: 2026-09-19 — R0.6 decision mutmut, partial measurement, workaround documented, tools/__init__.py added.*
