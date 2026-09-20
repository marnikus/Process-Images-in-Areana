# S0 — equivalence baseline for the staged chain (2026-09-21)

Plan of record: `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/` (`design.md` §9,
`quality-budget.md` §1, `tdd-interfaces.md` §D/§E) + round 1
`docs/archive/2026-09-20-live-processing-and-watcher-scope/`. Base commit of the chain: `528af87`
(`main`), branch `arena/01a0bf98-process-images-in-areana`.

S0 is the prerequisite, not a stage: bootstrap, then **measure** the tree so every stage S1…S10 starts
green and ends green. Everything below is measured, not assumed (`tdd-interfaces.md` §D last paragraph).

## 1. Bootstrap (quality-budget §1, verbatim)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt radon vulture coverage cognitive-complexity
npm ci
bash tools/stage_gate.sh --coverage      # the fast lane, wrapped (new in S0, see §4)
```

Sandbox facts: Python 3.11.2, node 22.22.3, PySide6 6.11.2 installed but **`PySide6.QtWidgets` cannot
load** (`libGL.so.1` missing; apt mirrors unreachable), so `app/ui/qt_compat.py` runs its dummy shim and
`tests/test_bridge_metaobject.py` skips (as designed for headless). The source-level slot count in
`tests/test_bridge_slots.py` (135) stays the active guard for the D-20/D-22 "0 new slots" budget.

## 2. What the tree at `528af87` really looked like (RED findings before any stage)

| # | Finding | Evidence | S0 action |
|---|---|---|---|
| F-1 | Runtime data tracked again: 2 `.pyc` + `config/{app_state,captcha_stats,cooldowns,undo}.json` (re-added by `528af87 upd`; I-43 had un-tracked them) | `tests/test_repo_hygiene.py::test_no_runtime_data_is_tracked` FAILS at base; `pre_push_check.sh` step 0 fails | `git rm --cached` (files stay on disk; `.gitignore` already lists them) |
| F-2 | `tools/quality_baseline.json` stored `max_cog = 0` for all 119 py entries that have functions — cognitive-complexity was never installed when it was recorded — so installing it per quality-budget §1 made the ratchet fail **119 files** ("grew 0→N") on an unchanged tree | `verify_quality.py --allow-legacy` at base: 119 fails, all `ratchet-max_cog` | re-measured `max_cog` for every entry (§3); highest value in the tree is **15** (= the RULE 16 line, none above) |
| F-3 | The gate's CC instrument was PATH-dependent: `try_radon_cc` ran bare `python -m radon`, while `tools/metrics_report.py` uses `sys.executable`. Baseline `max_cc` was recorded with the AST approximation; with the venv on PATH, radon disagreed on 21 files (15 up, 6 down) | same command with `.venv/bin` first on PATH: +15 `ratchet-max_cc` fails, e.g. `core/scanner.py` 7→10 | `try_radon_cc` now uses `sys.executable` (deterministic); `max_cc` re-measured with radon for the 21 entries (§3). No value exceeds 10 (`scanner.py` = 10 is legacy, untouched by the chain) |
| F-4 | Two per-file coverage floors were unreachable in this environment: `app/ui/qt_compat.py` 60.7 % floor vs 39.3 % measured (clipboard helpers covered only where PySide6 is absent **or** fully loadable), `app/browser/cdp/transport.py` 90.5 % vs 84.3 % (its services-side ImportError shim only runs where `PySide6.QtCore` is absent) | `verify_quality.py --coverage-ratchet` with fresh `coverage.json`: 2 `ratchet-coverage` fails | +6 tests in `tests/test_qt_compat.py` (fake `PySide6.QtWidgets/QtGui` modules exercise every clipboard arc) and +2 tests in `tests/test_qt_shim_fallback.py` (the transport source loaded under a probe name with `PySide6.QtCore` blocked — no reload of the live module). Environment-independent; floors now met with margin (89.3 % / 91.0 %) |
| F-5 | 4 production files are not in the baseline at all (`browser/processing_probe.py`, `core/progress.py`, `core/run_scope.py`, `services/await_processing.py`) and 2 `.js` files (78 on disk, 76 recorded) | `record_baseline` was last run before B10–B13 | left as is: unbaselined files are gated by the hard limits only, which is the status quo; recording them is an integrator decision for S10 |

No production file changed in S0. The plan's headroom table (`tdd-interfaces.md` §D) is confirmed on the
seven enforced size maxima: **0 ratchet breaches** on all 151 py files and all 78 js files.

## 3. Baseline instrument alignment — exactly what moved in `tools/quality_baseline.json`

Code unchanged at `528af87`; only the measuring instrument changed (radon + cognitive-complexity now
present, gate pinned to `sys.executable`). Reproduce with `tools/verify_quality.current_maxima()`.

* `max_cog`: 119 entries `0 → measured` (unmeasured, never "measured 0"). Max in tree 15.
* `max_cc` (radon replaces the AST approximation), 21 entries — up: `browser/probe_selectors.py` 1→2,
  `core/action_blocks.py` 7→8, `core/folder_ai.py` 5→6, `core/models.py` 3→4, `core/scanner.py` 7→10,
  `captcha_recording/{cohort 4→5, comparison 7→8, network 7→9, retention 6→7, store 4→5}`,
  `ui/panels/blocks_library.py` 6→7, `ui/panels/watcher_solver.py` 7→8, `ui/services/folder_ai_service.py`
  4→5, `utils/page_errors.py` 7→9, `utils/win_popup.py` 6→7; down (tightened): `browser/page_pool.py`
  10→9, `main.py` 2→1, `persistence/json_store.py` 5→4, `services/cooldown_service.py` 10→9,
  `services/single_job_runner.py` 9→7, `utils/hashing.py` 4→3.
* Nothing else moved: no `max_func_loc`, `max_class_loc`, `max_methods`, `max_nest`, `max_params`,
  coverage floor or JS entry changed. The global floor stays **86.36 / 82.33**.

## 4. `tools/stage_gate.sh` — the fast lane, wrapped

One command per stage (RULE 16 "gates on every production change"): hygiene → full `pytest`
(the frozen seams `test_bridge_slots`, `test_bridge_metaobject`, `test_cooldown_service.py:604-618`,
`test_page_pool.py` and the characterization goldens are in it) → `npm run test:js` whenever
`app/ui/web/` or `tests/js/` moved → `verify_quality.py --allow-legacy --coverage-ratchet
--changed-files <py+js changed vs base incl. the working tree>`. `--changed` alone diffs `base...HEAD`
and misses uncommitted work, so the wrapper computes the list itself and the gate can run **before** the
commit. `--coverage` regenerates `coverage.json` first (pre-push does the same).

## 5. Measured S0 numbers (after §2/§3, before S1)

| Lane | Command | Result |
|---|---|---|
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q` | **1,621 passed · 11 skipped** (base 1,613 + 8 S0 tests; skips: 3 headless-only `test_qt_compat`, 1 metaobject, 7 `test_verify_quality_tool` "no ancestor with gated app-file changes") |
| JS tests | `npm run test:js` | **240 pass · 0 fail** in 29 listed `.mjs` (35 on disk — L-7, S10) |
| Size/complexity | `.venv/bin/python tools/verify_quality.py --allow-legacy` | **0 fails** / 151 py + 78 js files |
| Coverage | `coverage run --branch --source=app -m pytest tests` | **87.14 % line / 83.38 % branch** (floor 86.36 / 82.33) |
| Duplication | `npx jscpd app --min-tokens 60` | **1.119 %** (23 groups; baseline 1.24 %) |
| Dead code | `vulture app tools/vulture_whitelist.py --min-confidence 90` | clean |
| Slot contract | `tests/test_bridge_slots.py` | 135 (unchanged) |

## 6. Test ledger delta introduced by S0 (outside the plan's 134/19 count)

`tests/test_qt_compat.py` +6, `tests/test_qt_shim_fallback.py` +2 — coverage-equivalence tests for
existing code (not RED tests: §E.1 applies only to stage tests). Plan ledger for S1…S10 is unchanged.
