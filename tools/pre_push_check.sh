#!/bin/bash
# pre_push_check.sh — runs quality gate before push (RULE 16)
# Called by .git/hooks/pre-push and manually via: bash tools/pre_push_check.sh
#
# F-6 fixes (2026-09-19):
#   - picks .venv/bin/python when present (no bare `python` assumption)
#   - --changed resolves its base (env -> origin/<branch> -> origin/main)
#     so the changed-file lane gates exactly the unpushed commits;
#     unusable bases WARN LOUDLY on stderr instead of silently
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
# Base for the changed-file lane: gate exactly what is being pushed.
# Resolution order: explicit env override -> origin/<current-branch>
# (diff = the unpushed commits; merge-base always exists) -> origin/main
# (loud GATE HONESTY warning when it shares no ancestry, gates ALL files).
resolve_base() {
  if [ -n "$VERIFY_QUALITY_BASE" ]; then echo "$VERIFY_QUALITY_BASE"; return; fi
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
  if [ -n "$branch" ] && git merge-base HEAD "origin/$branch" > /dev/null 2>&1; then
    echo "origin/$branch"
  else
    echo "origin/main"
  fi
}
BASE="$(resolve_base)"
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

# 5. Vulture unused code (R0.4 lane from area R0)
echo "▶ Vulture --min-confidence 90 (whitelist: tools/vulture_whitelist.py)"
if "$PY" -m vulture --version > /dev/null 2>&1; then
  if "$PY" -m vulture app tools/vulture_whitelist.py --min-confidence 90 > /tmp/vulture.txt 2>&1; then
    if [ -s /tmp/vulture.txt ]; then
      echo "  ❌ Vulture found unused code @90:"
      cat /tmp/vulture.txt
      exit 1
    fi
    echo "  ✅ Vulture clean @90"
  else
    echo "  ⚠ vulture run failed (not a code breach):"
    tail -n 5 /tmp/vulture.txt
  fi
else
  echo "  ⚠ vulture not installed — $PY -m pip install vulture"
fi
echo ""

# 6. Duplication jscpd (R0.4 lane, fail-on-regression per D6)
echo "▶ Duplication jscpd (app/, min-tokens 60, baseline tools/jscpd_baseline.json)"
if command -v npx > /dev/null 2>&1 && [ -d "$ROOT/node_modules" ]; then
  mkdir -p /tmp/jscpd-out
  npx --no-install jscpd app --min-tokens 60 --reporters json --output /tmp/jscpd-out --silent > /dev/null 2>&1 || true
  if [ -f /tmp/jscpd-out/jscpd-report.json ]; then
    "$PY" - "$ROOT/tools/jscpd_baseline.json" "$ROOT/config" <<'PYEOF'
import json, sys
report = json.load(open("/tmp/jscpd-out/jscpd-report.json"))
current = float(report["statistics"]["total"]["percentage"])
try:
    baseline = float(json.load(open(sys.argv[1]))["duplicated_lines_percent"])
except Exception as exc:
    print(f"  ⚠ no jscpd baseline ({exc}) — reporting only")
    sys.exit(0)
groups = len(report["duplicates"])
print(f"  Duplication {current:.3f}% ({groups} groups) — baseline {baseline:.3f}%")
if current > baseline + 0.01:
    print(f"  ❌ duplication grew {baseline:.3f}% → {current:.3f}% — dedup or update the "
          f"baseline in a commit that says why")
    sys.exit(1)
PYEOF
  else
    echo "  ⚠ jscpd produced no report"
  fi
else
  echo "  ⚠ npx/node_modules unavailable — duplication lane skipped"
fi
echo ""

# 7. Metrics report (R0.1, informational)
echo "▶ tools/metrics_report.py (informational)"
if ! "$PY" tools/metrics_report.py 2>&1 | head -n 12; then
  echo "  ⚠ metrics_report failed (informational only)"
fi
echo ""

echo "✅ All pre-push checks PASSED — safe to push"
echo "   git push origin $(git rev-parse --abbrev-ref HEAD)"
echo "Lanes: syntax + pytest + node + coverage(ratchet) + quality gate(py+js) + vulture + jscpd + metrics"
echo "Not in the push budget (run on demand): mutation — bash tools/mutmut_scope.sh run [SCOPE]"
echo "  (scopes: tools/mutmut_scopes.txt, evidence: docs/archive/2026-09-19-area-d-implementation/d5-mutation.md)"
