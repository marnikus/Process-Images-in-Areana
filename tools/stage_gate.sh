#!/usr/bin/env bash
# Fast lane for one stage of the S1..S10 chain (quality-budget.md §1).
# Usage: bash tools/stage_gate.sh [--js]
# Never runs --record-baseline: that is integrator-only (RULE 16 §16.5).
set -euo pipefail

PY=${PY:-.venv/bin/python}
[ -x "$PY" ] || PY=python3

echo "== 1/5 quality ratchet (changed files, legacy allowed, coverage ratchet)"
"$PY" tools/verify_quality.py --changed --allow-legacy --coverage-ratchet

echo "== 2/5 frozen seams (never edited: 134 slots, window table, cooldown wait)"
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q \
  tests/test_bridge_slots.py \
  tests/test_bridge_metaobject.py \
  tests/test_cooldown_service.py \
  tests/test_grid_layout.py

echo "== 3/5 unit + integration"
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q tests

echo "== 4/5 characterization goldens (equivalence gate)"
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q tests/characterization

if [ "${1:-}" = "--js" ]; then
  echo "== 5/5 JS lane"
  npm run test:js
else
  echo "== 5/5 JS lane skipped (no .js touched in this stage)"
fi

echo "OK — stage is gate-green"
