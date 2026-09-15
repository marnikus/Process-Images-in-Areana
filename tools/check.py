"""Full local gates: real QtCore and loopback CDP peer, no Chrome/account required."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "Process Images in Areana" / "Old App"
# Explicit retained-feature baseline. This is not the entire old app suite.
RETAINED_JS = (
    "test_sash_core.js",
    "test_sash_core_v2.js",
    "test_sash_drag.js",
    "test_sash_resize.js",
    "test_sash_grid_window_controls.js",
    "test_grid_persistence.js",
    "test_grid_close_autosave.js",
    "test_window_presets.js",
    "test_window_preset_ui.js",
    "test_preset_io_ui.js",
    "test_stack_dnd_migration.js",
    "test_url_toolbar.js",
)
# Real DOM/probe cases only. The separate BlockConfig class needs the full old
# Qt/action registry; it is explicitly outside this headless baseline (Step 7).
RETAINED_PYTHON = (
    ("test_find_click_visual.py", "TestFindPhase", "TestClickPhase", "TestInterpret"),
)


def run(command, *, cwd=ROOT):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(command, cwd=cwd, check=True, timeout=180)


def main():
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node is required for real retained workspace/probe tests; not skipped")
    report = ROOT / "coverage" / "coverage.json"
    report.parent.mkdir(exist_ok=True)
    report.unlink(missing_ok=True)
    python = sys.executable
    run([python, "-m", "ruff", "check", "src", "tests", "tools"])
    run([python, "-m", "ruff", "format", "--check", "src", "tests", "tools"])
    run([python, "-m", "mypy"])
    scripts = [
        f"src/image_queue/ui/js/{name}.js"
        for name in (
            "boot",
            "panels",
            "workspace",
            "workspace-view",
            "connect",
            "wire",
            "libraries",
            "stack-editor",
            "queue-view",
            "chrome-view",
            "features",
            "block-fields",
        )
    ]
    run([node, "node_modules/eslint/bin/eslint.js", *scripts])
    run([node, "node_modules/prettier/bin/prettier.cjs", "--check", *scripts])
    run(
        [
            python,
            "-m",
            "pytest",
            "--cov",
            "--cov-config=tools/headless.coveragerc",
            "--cov-report=term-missing",
            "--cov-report=json:coverage/coverage.json",
        ]
    )
    run([python, "tools/quality.py"])
    run([python, "tools/mutation_smoke.py"])
    os.environ["PYTHON"] = python
    run([node, "--test", "tests/js/workspace.test.cjs"])
    for name in RETAINED_JS:
        run([node, str(LEGACY / "tests" / name)], cwd=LEGACY)
    for name, *classes in RETAINED_PYTHON:
        run([python, str(LEGACY / "tests" / name), *classes], cwd=LEGACY)
    print("PASS: headless core, extracted workspace DOM integration and retained-system baseline")


if __name__ == "__main__":
    main()
