"""Gate-honesty tests for tools/verify_quality.py (B12, finding F-6).

Locks the two behaviours the pre-push flow depends on:
1. --changed with an unusable base ref falls back to ALL files with a LOUD
   stderr warning and a JSON `changed_fallback` reason — never silently.
2. --coverage-ratchet fails only on a DECREASE vs the baseline coverage;
   the absolute 80/75 (final D4 target) only warns in that mode.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "verify_quality.py"


def _usable_base():
    """Most recent ancestor whose diff to HEAD changes a gated app file.

    Derived from git at runtime — no hardcoded hashes, survives history
    rewrites (F-16). None when no such ancestor exists (tiny histories)."""
    try:
        ancestors = subprocess.run(
            ["git", "rev-list", "HEAD", "-n", "40"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=30,
        ).stdout.split()
        for anc in ancestors[1:]:
            diff = subprocess.run(
                ["git", "diff", "--name-only", f"{anc}...HEAD"],
                capture_output=True, text=True, cwd=str(ROOT), timeout=30,
            ).stdout.splitlines()
            if any(line.startswith("app/") and line.endswith(".py") for line in diff):
                return anc
    except Exception:
        pass
    return None


GOOD_BASE = _usable_base()
_needs_base = pytest.mark.skipif(not GOOD_BASE, reason="no ancestor with gated app-file changes")

# The full gated set, from the tool itself (no magic file counts — F-16).
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("verify_quality_under_test", TOOL)
_vq = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_vq)
GATED_ALL = len(_vq.all_app_files())


def run_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300,
    )


def coverage_file(tmp: Path, line_pct: float, branch_covered: int, branch_total: int) -> Path:
    cov = tmp / f"cov_{line_pct}_{branch_covered}.json"
    cov.write_text(json.dumps({"totals": {
        "percent_covered": line_pct,
        "covered_branches": branch_covered,
        "num_branches": branch_total,
    }}), encoding="utf-8")
    return cov


def baseline_file(tmp: Path, name: str, line: float, branch: float) -> Path:
    base = tmp / name
    base.write_text(json.dumps({
        "app/example.py": {"max_func_loc": 10, "max_class_loc": 0, "func_count": 3},
        "coverage": {"line": line, "branch": branch},
    }), encoding="utf-8")
    return base


@pytest.mark.unit
def test_changed_with_unusable_base_warns_loudly_not_silently():
    result = run_tool("--changed", "--base", "no-such-ref-anywhere", "--json")
    data = json.loads(result.stdout)
    # fallback happened, is explained, and is LOUD on stderr
    assert data["changed_fallback"], "fallback reason missing from JSON"
    assert "no merge-base" in data["changed_fallback"] or "failed" in data["changed_fallback"]
    assert "GATE HONESTY" in result.stderr
    assert "ALL" in result.stderr
    # and the fallback is real: ALL gated app files were checked
    assert data["files_checked"] == GATED_ALL


@_needs_base
@pytest.mark.unit
def test_changed_with_valid_base_no_fallback():
    result = run_tool("--changed", "--base", GOOD_BASE, "--json")
    data = json.loads(result.stdout)
    assert data["changed_fallback"] is None
    assert 0 < data["files_checked"] < GATED_ALL, "expected a real subset of changed files"


@_needs_base
@pytest.mark.unit
def test_coverage_ratchet_passes_when_above_baseline(tmp_path: Path):
    cov = coverage_file(tmp_path, 50.0, 400, 1000)
    base = baseline_file(tmp_path, "base_low.json", 45.0, 35.0)
    result = run_tool("--changed", "--base", GOOD_BASE, "--json",
                      "--coverage-file", str(cov),
                      "--coverage-ratchet", "--baseline", str(base))
    lanes = [b for b in json.loads(result.stdout)["breaches"] if b["type"] == "coverage"]
    assert lanes, "expected the absolute shortfalls as warnings"
    assert all(not b["fail"] for b in lanes), "above-baseline coverage must not fail"
    assert any("D4" in b["message"] for b in lanes)


@_needs_base
@pytest.mark.unit
def test_coverage_ratchet_fails_on_decrease(tmp_path: Path):
    cov = coverage_file(tmp_path, 50.0, 400, 1000)
    base = baseline_file(tmp_path, "base_high.json", 55.0, 30.0)
    result = run_tool("--changed", "--base", GOOD_BASE, "--json",
                      "--coverage-file", str(cov),
                      "--coverage-ratchet", "--baseline", str(base))
    lanes = [b for b in json.loads(result.stdout)["breaches"] if b["type"] == "coverage"]
    ratchet_fails = [b for b in lanes if b["fail"]]
    assert len(ratchet_fails) == 1 and ratchet_fails[0]["metric"] == "line"
    assert "never decrease" in ratchet_fails[0]["message"]


@_needs_base
@pytest.mark.unit
def test_coverage_absolute_mode_still_fails(tmp_path: Path):
    cov = coverage_file(tmp_path, 50.0, 400, 1000)
    base = baseline_file(tmp_path, "base_abs.json", 45.0, 35.0)
    result = run_tool("--changed", "--base", GOOD_BASE, "--json",
                      "--coverage-file", str(cov), "--baseline", str(base))
    lanes = [b for b in json.loads(result.stdout)["breaches"] if b["type"] == "coverage"]
    assert {b["metric"] for b in lanes if b["fail"]} == {"line", "branch"}


@pytest.mark.unit
def test_update_coverage_baseline_round_trip(tmp_path: Path):
    cov = coverage_file(tmp_path, 44.31, 979, 2900)
    base = baseline_file(tmp_path, "base_seed.json", 40.0, 30.0)
    result = run_tool("--update-coverage-baseline",
                      "--baseline", str(base), "--coverage-file", str(cov))
    assert "44.31" in result.stdout
    stored = json.loads(base.read_text(encoding="utf-8"))
    assert stored["coverage"] == {"line": 44.31, "branch": 33.76}
    assert "app/example.py" in stored, "existing per-file baseline keys must survive"


@pytest.mark.unit
def test_pre_push_script_has_syntax_valid_shell():
    """bash -n parses the pre-push script (RULE 8: the gate itself is tested)."""
    result = subprocess.run(["bash", "-n", str(ROOT / "tools" / "pre_push_check.sh")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_pre_push_script_gates_node_and_skips_loudly():
    """The node lane exists and its skip path is loud, never silent (F-10)."""
    script = (ROOT / "tools" / "pre_push_check.sh").read_text(encoding="utf-8")
    assert "npm run test:js" in script, "node lane missing from pre-push gate"
    assert "NODE LANE SKIPPED" in script, "skip path must warn loudly"
    # pytest lanes must not dirty the worktree mid-push (F-11)
    assert "-p no:cacheprovider" in script


@pytest.mark.unit
def test_update_baseline_refuses_to_lower_the_ratchet_floor(tmp_path: Path):
    """F-14: the maintenance flag must not be able to lower the floor."""
    cov_low = coverage_file(tmp_path, 20.0, 100, 1000)
    base = baseline_file(tmp_path, "base_floor.json", 44.31, 35.10)
    result = run_tool("--update-coverage-baseline",
                      "--baseline", str(base), "--coverage-file", str(cov_low))
    assert result.returncode != 0, "lowering the ratchet floor must fail"
    assert "LOWER" in result.stdout + result.stderr
    # baseline untouched by the refused run
    assert json.loads(base.read_text(encoding="utf-8"))["coverage"] == {"line": 44.31, "branch": 35.10}
    # equal line + higher branch is accepted (floor may only move up)
    cov_up = coverage_file(tmp_path, 44.31, 1020, 2900)
    ok = run_tool("--update-coverage-baseline",
                  "--baseline", str(base), "--coverage-file", str(cov_up))
    assert ok.returncode == 0
    assert json.loads(base.read_text(encoding="utf-8"))["coverage"]["branch"] > 35.10


@_needs_base
@pytest.mark.unit
def test_ratchet_with_missing_baseline_key_warns_not_silent(tmp_path: Path):
    """F-17a: no usable ratchet floor -> explicit warn lane + absolute fails."""
    base = tmp_path / "base_nokey.json"
    base.write_text(json.dumps({"app/example.py": {"max_func_loc": 10}}), encoding="utf-8")
    cov = coverage_file(tmp_path, 50.0, 400, 1000)
    result = run_tool("--changed", "--base", GOOD_BASE, "--json",
                      "--coverage-file", str(cov),
                      "--coverage-ratchet", "--baseline", str(base))
    lanes = [b for b in json.loads(result.stdout)["breaches"] if b["type"] == "coverage"]
    assert any(b["metric"] == "ratchet-unavailable" and not b["fail"] for b in lanes)
    assert {b["metric"] for b in lanes if b["fail"]} == {"line", "branch"}


@_needs_base
@pytest.mark.unit
def test_missing_coverage_file_is_a_warn_not_a_fail():
    result = run_tool("--changed", "--base", GOOD_BASE, "--json",
                      "--coverage-file", "/nonexistent/cov.json")
    cov = [b for b in json.loads(result.stdout)["breaches"] if b["type"] == "coverage"]
    assert len(cov) == 1 and cov[0]["metric"] == "missing" and not cov[0]["fail"]


@_needs_base
@pytest.mark.unit
def test_corrupt_coverage_file_reports_parse_error(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = run_tool("--changed", "--base", GOOD_BASE, "--json",
                      "--coverage-file", str(bad))
    cov = [b for b in json.loads(result.stdout)["breaches"] if b["type"] == "coverage"]
    assert len(cov) == 1 and cov[0]["metric"] == "parse-error" and not cov[0]["fail"]
