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


def exercise(folder):
    environment = dict(os.environ, PYTHONPATH=str(folder / "src"), PYTEST_ADDOPTS="")
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_urls.py"],
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
        shutil.copy(ROOT / "tests/test_urls.py", folder / "test_urls.py")
        (folder / "pytest.ini").write_text(
            "[pytest]\naddopts = --strict-markers\n", encoding="utf-8"
        )
        baseline = exercise(folder)
        if baseline.returncode != 0:
            raise SystemExit("Invalid mutation baseline:\n" + baseline.stdout + baseline.stderr)
        for name, old, new in MUTATIONS:
            path = folder / "src/image_queue/domain" / name
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                raise SystemExit(f"Mutation target changed; review experiment: {name}: {old}")
            path.write_text(original.replace(old, new), encoding="utf-8")
            shutil.rmtree(path.parent / "__pycache__", ignore_errors=True)
            result = exercise(folder)
            path.write_text(original, encoding="utf-8")
            shutil.rmtree(path.parent / "__pycache__", ignore_errors=True)
            if result.returncode != 1 or "ERROR" in result.stdout or "failed" not in result.stdout:
                raise SystemExit(
                    f"Survived/invalid mutation {name}: {old}\n{result.stdout}{result.stderr}"
                )
            print(f"Killed safety mutation: {name}: {old}")
    print(f"PASS: {len(MUTATIONS)} targeted mutations killed (not a full mutation score)")


if __name__ == "__main__":
    main()
