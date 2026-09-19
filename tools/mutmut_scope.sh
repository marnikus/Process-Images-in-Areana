#!/usr/bin/env bash
# D5 — scoped mutmut driver (design.md: services + core + browser/cdp_*).
#
# Usage:
#   bash tools/mutmut_scope.sh estimate            # print-time-estimates per scope
#   bash tools/mutmut_scope.sh run [SCOPE...]      # run scope(s), default all
#   bash tools/mutmut_scope.sh results             # aggregate saved per-scope results
#
# State: mutmut's mutants/ dir is wiped between scopes; per-scope summaries are
# saved to docs/archive/2026-09-19-area-d-implementation/d5-results/.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
MUT="$ROOT/.venv/bin/mutmut"
SCOPES_FILE="tools/mutmut_scopes.txt"
OUT_DIR="docs/archive/2026-09-19-area-d-implementation/d5-results"
DEFAULT_CFG="tools/mutmut_setup.cfg.default"
mkdir -p "$OUT_DIR"

# --- parse scope file -------------------------------------------------------
S_NAMES=()
declare -A S_SOURCES S_TESTS S_DONOT
cur=""
while IFS= read -r line; do
  case "$line" in
    ''|\#*) continue ;;
    SCOPE\ *) cur="${line#SCOPE }"; S_NAMES+=("$cur") ;;
    SOURCE\ *) [[ -n "$cur" ]] && S_SOURCES[$cur]="${S_SOURCES[$cur]:+${S_SOURCES[$cur]};}${line#SOURCE }" ;;
    DO_NOT\ *) [[ -n "$cur" ]] && S_DONOT[$cur]="${S_DONOT[$cur]:+${S_DONOT[$cur]};}${line#DO_NOT }" ;;
    TESTS\ *) [[ -n "$cur" ]] && S_TESTS[$cur]="${line#TESTS }" ;;
  esac
done < "$SCOPES_FILE"

write_config() { # $1 = scope name
  local src tst don
  src="${S_SOURCES[$1]//;/ }"; tst="${S_TESTS[$1]:-}"; don="${S_DONOT[$1]:-}"
  {
    echo "[mutmut]"
    local first=1 p
    for p in $src; do
      if [[ $first -eq 1 ]]; then echo "source_paths = $p"; first=0; else echo "   $p"; fi
    done
    echo "mutate_only_covered_lines = true"
    echo "timeout_multiplier = 12"
    echo "timeout_constant = 10"
    echo "also_copy = app"
    echo "            tests"
    echo "            tools"
    echo "            pytest.ini"
    if [[ -n "$don" ]]; then
      first=1
      for p in ${don//;/ }; do
        if [[ $first -eq 1 ]]; then echo "do_not_mutate = $p"; first=0; else echo "   $p"; fi
      done
    fi
    if [[ -n "$tst" ]]; then
      first=1
      for p in $tst; do
        if [[ $first -eq 1 ]]; then echo "pytest_add_cli_args_test_selection = $p"; first=0; else echo "   $p"; fi
      done
    fi
  } > setup.cfg
}

dump_scope_results() { # $1 = scope name — parse mutmut's mutants/*.meta JSON
  "$PY" - "$1" > "$OUT_DIR/$1.summary.json" <<'EOF'
import json, sys
from pathlib import Path

name = sys.argv[1]
status_by_exit = {1: "killed", 3: "killed", 37: "killed", 0: "survived",
                  5: "no_tests", 33: "no_tests", 34: "skipped",
                  35: "suspicious", 36: "timeout", -24: "timeout", 24: "timeout",
                  152: "timeout", 255: "timeout", -11: "segfault", -9: "segfault"}
counts, survivors, files = {}, [], {}
for meta in sorted(Path("mutants").rglob("*.meta")):
    try:
        data = json.loads(meta.read_text())
    except Exception:
        continue
    rel = str(meta.relative_to(Path("mutants")))[:-len(".meta")]
    per_file = {}
    for key, code in (data.get("exit_code_by_key") or {}).items():
        st = status_by_exit.get(code, f"exit_{code}")
        counts[st] = counts.get(st, 0) + 1
        per_file[rel] = per_file.get(rel, 0) + 1
        if st == "survived":
            survivors.append({"mutant": f"{rel}::{key}", "exit": code})
    files.update(per_file)
total = sum(counts.values())
killed = counts.get("killed", 0)
out = {"scope": name, "total": total, "status": counts, "mutants_per_file": files,
       "kill_rate": round(killed / total, 4) if total else None,
       "survivors": survivors}
print(json.dumps(out, indent=1))
EOF
  cp setup.cfg "$OUT_DIR/$name.setup.cfg" 2>/dev/null
}

restore_default_cfg() {
  if [[ -f "$DEFAULT_CFG" ]]; then cp "$DEFAULT_CFG" setup.cfg; fi
}

CMD="${1:-run}"
shift || true
WANT=("$@")
[[ ${#WANT[@]} -eq 0 ]] && WANT=("${S_NAMES[@]}")

wanted() { [[ " ${WANT[*]} " == *" $1 "* ]]; }

for name in "${S_NAMES[@]}"; do
  wanted "$name" || continue
  write_config "$name"
  case "$CMD" in
    estimate)
      echo "== scope: $name =="
      "$MUT" print-time-estimates 2>&1 | tail -6
      ;;
    run)
      if true; then
        echo "== scope: $name =="
        rm -rf mutants
        t0=$(date +%s)
        "$MUT" run --max-children 3 2>&1 | tail -3
        echo "scope_runtime_sec: $(( $(date +%s) - t0 ))"
        "$MUT" results --all > "$OUT_DIR/$name.results.txt" 2>&1
        dump_scope_results "$name"
        cat "$OUT_DIR/$name.summary.json" | head -20
        rm -rf mutants
      fi
      ;;
  esac
done

if [[ "$CMD" == "run" ]]; then restore_default_cfg; fi

# --- aggregate over saved summaries ------------------------------------------
if [[ "$CMD" == "results" ]]; then
  "$PY" - <<'EOF'
import json
from pathlib import Path
out = Path("docs/archive/2026-09-19-area-d-implementation/d5-results")
tot = counts = {}
print(f"{'scope':12s} {'total':>6s} {'killed':>7s} {'surv':>5s} {'noTst':>5s} {'other':>6s} {'kill%':>6s}")
grand_t = grand_k = 0
for f in sorted(out.glob("*.summary.json")):
    d = json.loads(f.read_text())
    c = d.get("status", {})
    k = c.get("killed", 0)
    tot = d.get("total", 0)
    other = tot - k - c.get("survived", 0) - c.get("no_tests", 0)
    grand_t += tot; grand_k += k
    pct = f"{100*k/tot:.1f}" if tot else "-"
    print(f"{d['scope']:12s} {tot:6d} {k:7d} {c.get('survived',0):5d} {c.get('no_tests',0):5d} {other:6d} {pct:>6s}")
    counts = c
if grand_t:
    print(f"{'TOTAL':12s} {grand_t:6d} {grand_k:7d} {'':5d} {'':5d} {'':6d} {100*grand_k/grand_t:5.1f}%")
EOF
fi
