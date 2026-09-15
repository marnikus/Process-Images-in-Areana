"""Targeted safety mutations in temporary source copies, never in the working tree.

Not a whole-project mutation score. A successful baseline is mandatory; only
pytest exit 1 with test failures (not collection errors) counts as a killed mutant.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = (
    (
        "connections.py",
        "target.url == row.exact_url",
        "target.url.lower() == row.exact_url.lower()",
    ),
    ("connections.py", 'target.kind == "page"', "True"),
    ("connections.py", "if not row.enabled:", "if False:"),
    ("connections.py", "else MatchStatus.AMBIGUOUS", "else MatchStatus.UNIQUE"),
    ("connections.py", "if len(ids) != len(set(ids)):", "if False:"),
    ("urls.py", "if parsed.username is not None or parsed.password is not None:", "if False:"),
)


CASES = tuple(
    ("domain/" + name, old, new, "tests/test_urls.py") for name, old, new in MUTATIONS
) + (
    (
        "workspace/queue.py",
        'choice.get("sha256") == source["sha256"] and bool(source["sha256"])',
        'bool(source["sha256"])',
        "tests/workspace/test_scanning.py::test_missing_changed_reconciliation_and_fingerprint_bound_selection",
    ),
    (
        "operations.py",
        'if command.get("sha256") != preview["sha256"]:',
        "if False:",
        "tests/workspace/test_operations.py",
    ),
    (
        "browser/session.py",
        'if info.get("targetId") != target_id or info.get("url") != exact_url:',
        "if False:",
        "tests/workspace/test_browser.py::test_failed_roundtrip_never_connected_or_replayed",
    ),
    (
        "domain/validation.py",
        "return type(left) is type(right) and left == right",
        "return left == right",
        "tests/workspace/test_libraries.py::test_boolean_to_number_is_a_real_edit_and_history_must_agree",
    ),
)


CASES += (
    (
        "automation/steps.py",
        'self.ledger.move(inputs["id"], "submit_intent")',
        "pass",
        "tests/workspace/test_execution.py::test_lifecycle_dispatches_actual_retained_dom_click_only_after_durable_intent",
    ),
    (
        "automation/engine.py",
        "if self.recovery_required:",
        "if False:",
        "tests/workspace/test_execution.py::test_restored_ready_attempt_requires_explicit_recovery",
    ),
    (
        "automation/visual.py",
        "roots.length !== 1",
        "roots.length === 0",
        "tests/workspace/test_visual.py::test_ambiguous_hidden_disabled_missing_never_click",
    ),
)


CASES += (
    (
        "automation/output_files.py",
        "os.link(temporary, path)",
        "os.replace(temporary, path)",
        "tests/workspace/test_output.py::test_publisher_never_replaces_existing_destination",
    ),
    (
        "automation/output_files.py",
        "actual != digest",
        "False",
        "tests/workspace/test_output.py::test_verification_detects_changed_bytes_extension_and_links",
    ),
)


def exercise(folder, suite):
    environment = dict(os.environ, PYTHONPATH=str(folder / "src"), PYTEST_ADDOPTS="")
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["NODE_PATH"] = str(ROOT / "node_modules")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", suite],
        cwd=folder,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
    )


def main():
    with tempfile.TemporaryDirectory(prefix="image-queue-mutations-") as temporary:
        folder = Path(temporary)
        shutil.copytree(
            ROOT / "src/image_queue",
            folder / "src/image_queue",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        (folder / "tests/workspace").mkdir(parents=True)
        shutil.copy(ROOT / "tests/test_urls.py", folder / "tests/test_urls.py")
        for name in (
            "conftest.py",
            "test_scanning.py",
            "test_operations.py",
            "test_browser.py",
            "test_libraries.py",
            "test_execution.py",
            "test_output.py",
            "test_visual.py",
        ):
            shutil.copy(ROOT / "tests/workspace" / name, folder / "tests/workspace" / name)
        (folder / "tools").mkdir()
        shutil.copy(ROOT / "tools/visual_fixture.cjs", folder / "tools/visual_fixture.cjs")
        (folder / "pytest.ini").write_text(
            "[pytest]\naddopts = --strict-markers\n", encoding="utf-8"
        )
        for suite in dict.fromkeys(case[3] for case in CASES):
            baseline = exercise(folder, suite)
            if baseline.returncode != 0:
                raise SystemExit("Invalid mutation baseline:\n" + baseline.stdout + baseline.stderr)
        for name, old, new, suite in CASES:
            path = folder / "src/image_queue" / name
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                raise SystemExit(f"Mutation target changed; review experiment: {name}: {old}")
            path.write_text(original.replace(old, new), encoding="utf-8")
            shutil.rmtree(path.parent / "__pycache__", ignore_errors=True)
            result = exercise(folder, suite)
            path.write_text(original, encoding="utf-8")
            shutil.rmtree(path.parent / "__pycache__", ignore_errors=True)
            if result.returncode != 1 or "ERROR" in result.stdout or "failed" not in result.stdout:
                raise SystemExit(
                    f"Survived/invalid mutation {name}: {old}\n{result.stdout}{result.stderr}"
                )
            print(f"Killed safety mutation: {name}: {old}")
    print(f"PASS: {len(CASES)} targeted mutations killed (not a full mutation score)")


if __name__ == "__main__":
    main()
