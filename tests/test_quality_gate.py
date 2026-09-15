"""Gate tests inject actual violating source, not just assertions about tool strings."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "quality", Path(__file__).parents[1] / "tools" / "quality.py"
)
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def test_clean_source_passes():
    assert quality.inspect_source("def sample(value):\n    return value + 1\n") == []


@pytest.mark.parametrize(
    "source,expected",
    [
        ("def sample(a,b,c,d,e):\n    return a\n", "parameters"),
        ("def sample():\n" + "    x = 1\n" * 31, "function lines"),
        ("class Sample:\n" + "    x = 1\n" * 151, "class lines"),
        (
            "class Sample:\n" + "".join(f"    def m{i}(self): return {i}\n" for i in range(16)),
            "methods",
        ),
        (
            "def sample(a):\n"
            + "".join("    " * n + "if a:\n" for n in range(1, 6))
            + "                        return a\n",
            "nesting",
        ),
        ("def sample(a):\n" + "    if a: pass\n" * 11, "CC"),
        ("def sample(a):\n" + "    if a: pass\n" * 16, "cognitive"),
    ],
)
def test_gate_rejects_real_violations(source, expected):
    assert any(expected in failure for failure in quality.inspect_source(source))


def test_keyword_only_and_variadic_parameters_count():
    failures = quality.inspect_source("def sample(self,a,b,*,c,d,e):\n    pass\n")
    assert any("parameters" in failure for failure in failures)
    assert quality.inspect_source("def sample(self,a,b,*args,**kwargs):\n    pass\n") == []


@pytest.mark.parametrize(
    "source", ["import sqlite3", "from PySide6 import QtCore", "import pathlib"]
)
def test_pure_domain_cannot_import_infrastructure(source):
    assert quality.inspect_source(source, domain=True)


def test_production_scope_cannot_silently_be_empty(tmp_path):
    assert quality.check_production(tmp_path)
    (tmp_path / "sample.py").write_text("def sample(a):\n    return a\n", encoding="utf-8")
    assert quality.check_production(tmp_path) == []


def test_independent_coverage_floors():
    report = {
        "files": {
            "src/image_queue/domain/sample.py": {
                "summary": {
                    "covered_lines": 95,
                    "num_statements": 100,
                    "covered_branches": 80,
                    "num_branches": 100,
                }
            }
        }
    }
    assert quality.coverage_failures(report) == ["Domain branches: 80.00% < 85%"]
    report["files"]["src/image_queue/domain/sample.py"]["summary"]["covered_branches"] = 85
    assert quality.coverage_failures(report) == []
    assert quality.coverage_failures({"files": {}})


def test_nested_functions_cannot_hide_complexity():
    source = "def outer(a):\n    def inner():\n" + "        if a: pass\n" * 11
    assert any("inner: CC" in failure for failure in quality.inspect_source(source))


def test_domain_cannot_import_application_side_effects():
    assert quality.inspect_source("from image_queue.cli import main", domain=True)
    assert quality.inspect_source("from image_queue.domain import urls", domain=True) == []
