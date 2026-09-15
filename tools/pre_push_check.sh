#!/bin/bash
# pre_push_check.sh — runs quality gate before push (RULE 16)
# Called by .git/hooks/pre-push and manually via: bash tools/pre_push_check.sh

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Arena Quality Gate — pre-push check (RULE 16) ==="
echo "Docs: docs/current/AGENT_RULES.md RULE 16"
echo ""

# 1. Python syntax compile
echo "▶ Checking Python syntax..."
python -m py_compile app/browser/dom_highlight.py app/browser/probe_requests.py app/browser/visual_click.py app/core/action_blocks.py app/ui/bridge.py app/browser/cdp_arena.py app/core/layout_service.py
echo "  ✅ Syntax ok"
echo ""

# 2. Quality gate (size, complexity, params, methods, nesting, anti-gaming)
# Per RULE 16: every production change must be verified. We check only changed files vs main with legacy allowed (grandfathered).
# Full check (all files) can be run manually: python tools/verify_quality.py
# Changed check ensures new code meets gates, legacy is allowed if not increased (baseline in tools/quality_baseline.json)
echo "▶ Running tools/verify_quality.py --changed --allow-legacy..."
if python tools/verify_quality.py --changed --allow-legacy; then
  echo "  ✅ Quality gate passed (changed files)"
else
  echo "  ❌ Quality gate FAILED on changed files — fix before push"
  echo "  See docs/current/AGENT_RULES.md RULE 16, RULE 19 remediation order"
  echo "  To see all files: python tools/verify_quality.py"
  exit 1
fi
echo ""

# 3. Tests
echo "▶ Running pytest..."
if python -m pytest tests -q; then
  echo "  ✅ Tests passed"
else
  echo "  ❌ Tests FAILED"
  exit 1
fi
echo ""

# 4. Coverage (if coverage installed)
if python -m coverage --version > /dev/null 2>&1; then
  echo "▶ Running coverage..."
  QT_QPA_PLATFORM=offscreen python -m coverage run --branch --source=app -m pytest tests -q
  python -m coverage json -o coverage.json
  echo "  Coverage report generated coverage.json"
  # Re-run quality gate to check coverage thresholds
  echo "▶ Checking coverage thresholds..."
  python tools/verify_quality.py --json | python -c "import json,sys; data=json.load(sys.stdin); fails=[b for b in data['breaches'] if b.get('fail') and b.get('type')=='coverage']; sys.exit(1 if fails else 0)"
  if [ $? -eq 0 ]; then
    echo "  ✅ Coverage ok"
  else
    echo "  ❌ Coverage below threshold"
    python tools/verify_quality.py
    exit 1
  fi
else
  echo "⚠ coverage not installed — skipping coverage check (install via pip install coverage)"
fi

echo ""
echo "✅ All pre-push checks PASSED — safe to push"
echo "   git push origin $(git rev-parse --abbrev-ref HEAD)"
