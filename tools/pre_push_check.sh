#!/usr/bin/env bash
# pre_push_check.sh — D6 laned quality gate (design.md D6, total budget < 3 min)
#
# Lanes (fail fast):
#   1 compile      compileall over app/
#   2 tests+cov    pytest (full suite — fast lane ≈ full here) -> coverage.json
#   3 py-gate      verify_quality --changed --allow-legacy
#                  (baseline v2 ratchet + per-file coverage ratchet + totals)
#   4 js-gate      acorn gate over changed JS (ratchet vs baseline "js" section)
#   5 js-tests     node --test tests/js/*
#   6 vulture      @90, NEW findings only (tools/vulture_whitelist.py)
#   7 dup          jscpd dup-% vs tools/jscpd_baseline.json
#
# Requires venv on PATH (python, pytest, coverage, vulture) and node (acorn, jscpd).
# Manual: bash tools/pre_push_check.sh

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

T0=$(date +%s)
declare -a LANE_NAMES LANE_TIMES
FAILED_LANE=""

# changed files vs origin/main (+ worktree), same logic as verify_quality.py
changed_files() {
  local base
  base=$(git merge-base origin/main HEAD 2>/dev/null)
  if [ -n "$base" ]; then
    git diff --name-only "$base...HEAD" 2>/dev/null
  else
    # no merge base (e.g. re-rooted sandbox history): everything under app/
    git ls-files -- app 2>/dev/null
  fi
  git diff --name-only HEAD 2>/dev/null
  git diff --cached --name-only 2>/dev/null
  git ls-files --others --exclude-standard -- app 2>/dev/null
}

run_lane() { # $1 name, $2 fn
  local name="$1" fn="$2" t
  t=$(date +%s)
  echo ""
  echo "▶ [$name]..."
  if "$fn"; then
    LANE_NAMES+=("$name"); LANE_TIMES+=($(( $(date +%s) - t )))
    echo "  ✅ $name ok ($(( $(date +%s) - t ))s)"
  else
    FAILED_LANE="$name"
    echo "  ❌ $name FAILED after $(( $(date +%s) - t ))s"
    return 1
  fi
}

lane_compile() {
  python -m compileall -q app
  find app -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
}

lane_tests_cov() {
  # Full suite under branch coverage (this repo's fast lane ≈ full suite: only 4
  # tests are slow/e2e-tagged, ~90 s either way — full keeps the ratchet's
  # coverage floor consistent with the baseline's measurement).
  if python -m coverage run --branch --source=app -m pytest -q -p no:cacheprovider; then
    python -m coverage json -o coverage.json >/dev/null
  fi
}

lane_py_gate() {
  python tools/verify_quality.py --changed --allow-legacy
}

lane_js_gate() {
  local files
  files=$(changed_files | grep -E '^app/ui/web/js/.*\.js$' | sort -u || true)
  if [ -z "$files" ]; then
    echo "  (no changed JS)"
    return 0
  fi
  echo "  changed JS: $(echo "$files" | wc -l) file(s)"
  node tools/js_gate.mjs --root . --changed $files
}

lane_js_tests() {
  npm run test:js --silent
}

lane_vulture() {
  python - <<'EOF'
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "tools")
from vulture_whitelist import WHITELIST, parse_vulture_output  # noqa: E402

res = subprocess.run([sys.executable, "-m", "vulture", "app", "--min-confidence", "90"],
                     capture_output=True, text=True)
findings = parse_vulture_output(res.stdout)
whitelisted = set(WHITELIST)
new = sorted(findings - whitelisted)
stale = sorted(whitelisted - findings)
for f, n in stale:
    print(f"  (stale whitelist entry: {f} {n})")
if new:
    print(f"NEW vulture @90 findings ({len(new)}):")
    for f, n in new:
        print(f"  {f}: {n}")
    print("Fix them or accept intentionally: python tools/vulture_whitelist.py --update")
    sys.exit(1)
print(f"  vulture @90: {len(findings)} finding(s), all whitelisted" if findings else "  vulture @90: clean")
EOF
}

lane_dup() {
  npx jscpd app --silent --reporters json --output jscpd-out >/dev/null
  python - jscpd-out/jscpd-report.json tools/jscpd_baseline.json <<'EOF'
import json
import sys

report = json.load(open(sys.argv[1]))
base = json.load(open(sys.argv[2]))
total = report["statistics"].get("total") or {}
lines = total.get("lines") or sum(f["lines"] for f in report["statistics"]["formats"].values())
dup = total.get("duplicatedLines") or sum(f["duplicatedLines"] for f in report["statistics"]["formats"].values())
cur = dup / lines * 100
base_pct = base["duplicated_lines_percent"]
print(f"  jscpd: {cur:.2f}% duplicated lines (baseline {base_pct:.2f}%)")
if cur > base_pct + 0.05:  # 0.05pp noise tolerance
    print("Duplication grew vs baseline — dedup before push (or regenerate the "
          "baseline intentionally with a dedup commit).")
    sys.exit(1)
EOF
  local rc=$?
  rm -rf jscpd-out
  return $rc
}

echo "=== Arena Quality Gate — pre-push check (D6 lanes) ==="
echo "Docs: docs/current/AGENT_RULES.md RULE 16"

run_lane compile lane_compile && \
run_lane "tests+cov" lane_tests_cov && \
run_lane "py-gate" lane_py_gate && \
run_lane "js-gate" lane_js_gate && \
run_lane "js-tests" lane_js_tests && \
run_lane vulture lane_vulture && \
run_lane dup lane_dup || {
  echo ""
  echo "❌ Pre-push checks FAILED in lane: $FAILED_LANE"
  echo "   Remediation order (RULE 19): nesting → CC → cognitive → size; regressions → restore shape"
  exit 1
}

ELAPSED=$(( $(date +%s) - T0 ))
TIMES=""
for i in "${!LANE_NAMES[@]}"; do
  TIMES+="${LANE_NAMES[$i]}:${LANE_TIMES[$i]}s "
done
echo ""
echo "Lane times: ${TIMES}| total ${ELAPSED}s"
if [ $ELAPSED -gt 180 ]; then
  echo "⚠ total gate time ${ELAPSED}s exceeds the 3-minute budget (D6) — investigate"
fi
echo ""
echo "✅ All pre-push checks PASSED — safe to push"
echo "   git push origin $(git rev-parse --abbrev-ref HEAD)"
