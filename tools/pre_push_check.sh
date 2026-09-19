#!/bin/bash
# pre_push_check.sh — runs quality gate before push (RULE 16)
# Called by .git/hooks/pre-push and manually via: bash tools/pre_push_check.sh
#
# F-6 fixes (2026-09-19):
#   - picks .venv/bin/python when present (no bare `python` assumption)
#   - --changed gets an explicit --base and the gate now WARNs LOUDLY on
#     stderr instead of silently falling back to all files
#   - node lane: npm run test:js gates the JS production code too
#   - coverage is generated FRESH before the single gate pass and uses the
#     RATCHET lane mid-round (fail only on decrease vs the baseline
#     'coverage' key; the absolute 80/75 stays the final D4 target and only
#     warns here until D4 lands)

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Python picker: repo venv first, then python3, then python
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 > /dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi
echo "Using python: $PY"

echo "=== Arena Quality Gate — pre-push check (RULE 16) ==="
echo "Docs: docs/current/AGENT_RULES.md RULE 16"
echo ""

# 1. Python syntax compile
echo "▶ Checking Python syntax..."
"$PY" -m py_compile app/browser/dom_highlight.py app/browser/probe_requests.py app/browser/visual_click.py app/core/action_blocks.py app/ui/bridge.py app/browser/cdp_arena.py app/core/layout_service.py
echo "  ✅ Syntax ok"
echo ""

# 2. Tests (fast lane — plain pytest, fails early with readable output)
echo "▶ Running pytest..."
if QT_QPA_PLATFORM=offscreen "$PY" -m pytest tests -q -p no:cacheprovider; then
  echo "  ✅ Tests passed"
else
  echo "  ❌ Tests FAILED"
  exit 1
fi
echo ""

# 2b. Node lane (RULE 16: JS in app/ui/web/js is production code too).
# Loud graceful skip when the runner is unavailable — never a silent pass.
if command -v npm > /dev/null 2>&1 && [ -d "$ROOT/node_modules" ]; then
  echo "▶ Running node tests (npm run test:js)..."
  if npm run test:js --silent; then
    echo "  ✅ Node tests passed"
  else
    echo "  ❌ Node tests FAILED"
    exit 1
  fi
else
  echo "⚠⚠ NODE LANE SKIPPED: npm or node_modules unavailable —"
  echo "    JS production code (app/ui/web/js) was NOT gated. Install Node +"
  echo "    run 'npm ci' before trusting this push for JS changes."
fi
echo ""

# 3. Coverage (fresh, branch-aware) — generated BEFORE the gate so the
#    gate's coverage lanes always judge current data, never a stale file.
if "$PY" -m coverage --version > /dev/null 2>&1; then
  echo "▶ Generating fresh coverage..."
  QT_QPA_PLATFORM=offscreen "$PY" -m coverage run --branch --source=app -m pytest tests -q -p no:cacheprovider
  "$PY" -m coverage json -o coverage.json
  echo "  ✅ Coverage report generated (coverage.json)"
else
  echo "⚠ coverage not installed — gate coverage lanes will warn (pip install coverage)"
fi
echo ""

# 4. Quality gate — ONE authoritative pass (RULE 16):
#    sizes/complexity on changed files vs BASE (legacy grandfathered via
#    tools/quality_baseline.json) + coverage RATCHET (fail on decrease;
#    absolute 80/75 = final D4 target, warns mid-round).
#    If BASE shares no ancestry with HEAD the gate prints a LOUD stderr
#    warning and gates ALL files — no silent fallback.
BASE="${VERIFY_QUALITY_BASE:-origin/main}"
echo "▶ Running tools/verify_quality.py --changed --base $BASE --allow-legacy --coverage-ratchet..."
if "$PY" tools/verify_quality.py --changed --base "$BASE" --allow-legacy --coverage-ratchet; then
  echo "  ✅ Quality gate passed (changed files vs $BASE, coverage ratchet)"
else
  echo "  ❌ Quality gate FAILED — fix before push"
  echo "  See docs/current/AGENT_RULES.md RULE 16, RULE 19 remediation order"
  echo "  To see all files: $PY tools/verify_quality.py"
  exit 1
fi

echo ""
echo "✅ All pre-push checks PASSED — safe to push"
echo "   git push origin $(git rev-parse --abbrev-ref HEAD)"
