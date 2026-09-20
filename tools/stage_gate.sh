#!/bin/bash
# stage_gate.sh — the FAST LANE every stage S1…S9 of the staged chain must pass
# (docs/archive/2026-09-20-dynamic-urls-and-worker-debug/quality-budget.md §1,
# design.md §9.1, RULE 16 "gates on every production change").
#
#   bash tools/stage_gate.sh              # pytest + gate on changed files (+ node when JS moved)
#   bash tools/stage_gate.sh --coverage   # same, but coverage.json is regenerated first so the
#                                         # coverage-ratchet lanes judge FRESH data (use before a commit
#                                         # that touches production code — RULE 16 "never decrease")
#
# What it pins down (S0 equivalence baseline, docs/archive/2026-09-21-staged-chain-implementation/S0-baseline.md):
#   * one interpreter for everything: .venv/bin/python (the gate's radon/cognitive instruments live there)
#   * "changed" = working tree + index + commits since the chain's base — NOT only committed work, so the
#     gate can run BEFORE the commit (verify_quality --changed diffs base...HEAD, which misses the tree)
#   * the node lane runs whenever a .js/.mjs/.html file moved (tests/js is production evidence too)
#   * repo hygiene (pre_push_check step 0) runs every time — the base tree had tracked runtime data
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "❌ no .venv — bootstrap first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt radon vulture coverage cognitive-complexity"; exit 2; }

WITH_COVERAGE=0
for arg in "$@"; do
  case "$arg" in
    --coverage) WITH_COVERAGE=1 ;;
    *) echo "unknown argument: $arg"; exit 2 ;;
  esac
done

# Base of the chain: explicit env, else the merge-base with origin/main.
BASE="${VERIFY_QUALITY_BASE:-$(git merge-base HEAD origin/main 2>/dev/null || echo origin/main)}"
echo "=== stage gate (fast lane) — base $(git rev-parse --short "$BASE") → $(git rev-parse --short HEAD)+tree ==="

# 0. Hygiene (mirrors tools/pre_push_check.sh step 0 / tests/test_repo_hygiene.py)
LEAK="$(git ls-files -- config logs 'arena webpages' '*.pyc' '*__pycache__*' | grep -v '^config/.gitkeep$' || true)"
if [ -n "$LEAK" ]; then echo "❌ runtime data tracked — git rm --cached:"; echo "$LEAK" | head -n 20; exit 1; fi

# 1. Changed files = committed since BASE + staged + unstaged + untracked (app/ only is gated)
CHANGED="$( { git diff --name-only "$BASE"; git ls-files --others --exclude-standard; } | sort -u )"
PY_CHANGED="$(echo "$CHANGED" | grep -E '^app/.*\.py$' || true)"
JS_CHANGED="$(echo "$CHANGED" | grep -E '^app/ui/web/.*\.js$' || true)"
WEB_MOVED="$(echo "$CHANGED" | grep -E '^(app/ui/web/|tests/js/)' || true)"
echo "changed: $(echo "$PY_CHANGED" | grep -c . || true) py, $(echo "$JS_CHANGED" | grep -c . || true) js (web/tests-js moved: $(echo "$WEB_MOVED" | grep -c . || true))"

# 2. pytest — the whole suite: the frozen seams (test_bridge_slots, test_bridge_metaobject,
#    test_cooldown_service, test_page_pool, characterization goldens) are IN it, so no stage
#    can go green on its own tests while breaking a seam it did not mean to touch.
if [ "$WITH_COVERAGE" = 1 ]; then
  echo "▶ pytest under coverage (fresh coverage.json)…"
  QT_QPA_PLATFORM=offscreen "$PY" -m coverage run --branch --source=app -m pytest tests -q -p no:cacheprovider
  "$PY" -m coverage json -o coverage.json -q
else
  echo "▶ pytest…"
  QT_QPA_PLATFORM=offscreen "$PY" -m pytest tests -q -p no:cacheprovider
fi

# 3. Node lane whenever the web tree moved (RULE 16: app/ui/web/js is production code)
if [ -n "$WEB_MOVED" ]; then
  echo "▶ npm run test:js…"
  [ -d node_modules ] || { echo "❌ node_modules missing — npm ci"; exit 1; }
  npm run test:js --silent | tail -n 8
fi

# 4. Quality gate on exactly the changed app files (py + js); coverage lanes in ratchet mode.
#    With no changed app files the gate still runs the coverage lanes + JS ratchet via --js.
echo "▶ verify_quality (changed files, legacy-aware, coverage ratchet)…"
FILES="$(printf '%s\n%s\n' "$PY_CHANGED" "$JS_CHANGED" | grep . || true)"
if [ -n "$FILES" ]; then
  # shellcheck disable=SC2086
  "$PY" tools/verify_quality.py --allow-legacy --coverage-ratchet --changed-files $FILES
else
  "$PY" tools/verify_quality.py --allow-legacy --coverage-ratchet --changed-files --js
fi
echo "✅ stage gate passed"
