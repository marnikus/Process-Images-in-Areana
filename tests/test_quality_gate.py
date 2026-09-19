"""D6 negative tests — the gate must fail on the regressions it exists to catch.

Subprocess against tmp_path fixtures via the tools' --root flag:
  1. 31-LOC function in a baseline file (regression)      -> verify_quality fails
  2. 40-LOC JS function (new symbol)                      -> js_gate fails
  3. per-file coverage drop below baseline                -> verify_quality fails
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VERIFY = REPO / "tools" / "verify_quality.py"
JS_GATE = REPO / "tools" / "js_gate.mjs"
BASELINE = REPO / "tools" / "baseline_update.py"

ALPHA_30 = (
    "def alpha(a, b):\n"
    "    out = a\n"
    + "".join(f"    out += {i}  # l{i}\n" for i in range(27))
    + "    return out\n"
)

ALPHA_31 = (
    "def alpha(a, b):\n"
    "    out = a\n"
    + "".join(f"    out += {i}  # l{i}\n" for i in range(28))
    + "    return out\n"
)

JS_40 = (
    "export function oversized(v) {\n"
    "  let total = v;\n"
    + "".join(f"  const t{i} = v + {i}; // l{i}\n" for i in range(36))
    + "  return total;\n"
    "}\n"
)


def _build_repo(root: Path, alpha: str = ALPHA_30, js: str = "export const ok = 1;\n",
                coverage: str | None = None) -> None:
    (root / "app" / "pkg").mkdir(parents=True)
    (root / "app" / "ui" / "web" / "js").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "pkg" / "__init__.py").write_text("")
    (root / "app" / "pkg" / "mod_a.py").write_text(alpha)
    (root / "app" / "ui" / "web" / "js" / "a.js").write_text(js)
    if coverage is not None:
        (root / "coverage.json").write_text(coverage)


def _write_coverage(root: Path, file_pct: float) -> None:
    (root / "coverage.json").write_text(json.dumps({
        "totals": {"percent_covered": file_pct, "covered_branches": 0, "num_branches": 0},
        "files": {"app/pkg/mod_a.py": {"summary": {"percent_covered": file_pct}}},
    }))


def _run_baseline(root: Path) -> None:
    subprocess.run([sys.executable, str(BASELINE), "--root", str(root)],
                   check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _build_repo(tmp_path)
    return tmp_path


def _gate(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VERIFY), "--root", str(root), *args],
                          capture_output=True, text=True)


@pytest.mark.unit
def test_gate_passes_on_unchanged_baseline_file(repo: Path):
    _run_baseline(repo)
    res = _gate(repo, "--changed-files", "app/pkg/mod_a.py", "--allow-legacy")
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.unit
def test_grown_function_in_baseline_file_fails(repo: Path):
    """30-LOC baseline function grown to 31 must fail the ratchet."""
    _run_baseline(repo)
    (repo / "app" / "pkg" / "mod_a.py").write_text(ALPHA_31)
    res = _gate(repo, "--changed-files", "app/pkg/mod_a.py", "--allow-legacy")
    assert res.returncode == 1
    assert "regressed" in res.stdout


@pytest.mark.unit
def test_per_file_coverage_drop_fails(repo: Path):
    """Per-file line coverage below its baseline value must fail."""
    _write_coverage(repo, 95.0)
    _run_baseline(repo)
    _write_coverage(repo, 80.0)
    res = _gate(repo, "--changed-files", "app/pkg/mod_a.py", "--allow-legacy")
    assert res.returncode == 1
    assert "below baseline" in res.stdout


node = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


@node
@pytest.mark.unit
def test_40loc_js_function_fails(repo: Path):
    (repo / "app" / "ui" / "web" / "js" / "a.js").write_text(JS_40)
    res = subprocess.run(["node", str(JS_GATE), "--root", str(repo),
                          "--changed", "app/ui/web/js/a.js"],
                         capture_output=True, text=True)
    assert res.returncode == 1
    assert "loc 40 > 30" in res.stdout


@node
@pytest.mark.unit
def test_js_gate_passes_on_small_functions(repo: Path):
    res = subprocess.run(["node", str(JS_GATE), "--root", str(repo),
                          "--changed", "app/ui/web/js/a.js"],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
