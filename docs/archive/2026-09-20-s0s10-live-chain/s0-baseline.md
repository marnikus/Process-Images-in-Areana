# S0 baseline evidence — 2026-09-20 (branch `arena/01a0bf4d-process-images-in-areana`)

Base: `528af87` (== origin/main, single squashed commit). No production file changed in S0.

## Commands and results (all green at S0 close)

| Gate | Command | Result |
|---|---|---|
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -p no:cacheprovider` | **1617 passed, 8 skipped**, 0 failed (110 s) |
| JS tests | `npm run test:js` | **240 pass, 0 fail** (29 listed files) |
| Coverage | `coverage run --branch --source=app -m pytest` + `coverage json` | **87.05 line / 83.25 branch** (floors 86.36 / 82.33) |
| Quality gate | `.venv/bin/python tools/verify_quality.py --allow-legacy --coverage-ratchet` | **0 fails, 0 warns** (151 py files, 78 js files) |
| Slot contract | `tests/test_bridge_slots.py` | **135** frozen slots, packing exact |
| Duplication | `jscpd app --min-tokens 60` | **1.119 %**, 23 groups (ceiling 1.24 %) |
| Goldens | inside pytest (`tests/characterization/`) | 12/12 green |

Env: Python 3.11.2 (fresh `.venv`, `pip install -r requirements.txt radon vulture
coverage pyflakes`), Node v22.22.3 (`npm ci`, 152 packages), PySide6 6.11.2 with
QtWidgets unimportable (no libGL) ⇒ qt_compat **shim active**. `cognitive-complexity`
deliberately NOT installed: the recorded baseline stores max_cog 0 for all 147
entries (lib-absent record); installing 1.3.0 fails 119 ratchet entries on tool drift.
Cognitive ≤15 is enforced per new/edited symbol by explicit scan instead (S1…S9 stage
gates; S10 decides on a re-record with a stated reason).

## RED proof captured at baseline (no workaround added)

- `app/ui/panels/page_pool.py:147` still calls `self._schedule_coro(...)`; repo-wide
  `grep -rn _schedule_coro app/` ⇒ exactly that one hit (L-1 open).
- `tests/test_panel_browser_tabs.py` builds hosts with `_schedule_coro=` 5 times (L-6 open).
- `index.html` still declares the orphan `winPagePool` / `data-window="page_pool"` (L-5 open).
- `tests/js/test_captcha_saved_page.mjs` + `tests/js/test_title_fit.mjs` on disk but
  unlisted in `package.json` (29 listed of 35; other 4 unlisted are harnesses — L-7 open).
- `WIN_ICONS` dead table still in `js/sash-grid.js` (L-8 open).

## S0 repairs (test/hygiene only)

1. Untracked 6 runtime files re-added by the squashed commit (kept on disk):
   `config/app_state.json`, `config/captcha_stats.json`, `config/cooldowns.json`,
   `config/undo.json`, 2 `.pyc`. Fixed `test_no_runtime_data_is_tracked`.
2. `tests/test_qt_compat.py`: headless-only skipif now checks the shim
   (`QFileDialog is None`) instead of package presence. +3 tests run here.
3. `tests/test_qt_shim_fallback.py`: new `test_transport_import_without_qt` pins the
   CDP transport Qt fallback via forced ImportError (env-independent).
   Before → after: qt_compat cov 39.29 → 62.50 (floor 60.71); transport cov
   84.27 → 91.01 (floor 90.45); suite 1613/11 → 1617/8; gate 2 fails → 0 fails.

## §D re-measure (gate's own `current_maxima`, 25 plan-touched files)

All enforced maxima match the recorded baseline except `single_job_runner.py`
max_cc 9 → 7 (shrink, legal). Soft-only (unenforced) moves: run_state 417/33 →
423/34, run_control 275 → 279, queue_scan 315/25 → 310/24, models 292/14 → 272/11,
batch_orchestrator 492/38 → 489/37, multi_page_dispatcher 398 → 402. Full table in
the S0 commit message trailer / this folder's `implementation-record.md`.
