"""Probe tests — run real JS through node harness against DOM stub."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.browser.output_probes import (
    JS_CHECK_NEW_OUTPUT_V4,
    build_baseline_js,
    build_check_js,
    build_scroll_bottom_js,
)


def test_builders_return_evaluate_expressions():
    assert build_baseline_js().startswith(";(")
    assert "JOB-ID" in JS_CHECK_NEW_OUTPUT_V4
    assert "validAbove" in JS_CHECK_NEW_OUTPUT_V4
    assert "fallbackDetails" in JS_CHECK_NEW_OUTPUT_V4
    assert "div.flex-col-reverse" not in JS_CHECK_NEW_OUTPUT_V4
    assert "ol.flex-col-reverse, div" not in JS_CHECK_NEW_OUTPUT_V4
    expr = build_check_js(["k1"], "ABC123")
    assert "ABC123" in expr
    assert "k1" in expr
    assert build_scroll_bottom_js().startswith(";")


def test_js_syntax_valid_via_node():
    if not shutil.which("node"):
        pytest.skip("node not available")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write("const probe = " + JS_CHECK_NEW_OUTPUT_V4 + ";")
        path = f.name
    try:
        proc = subprocess.run(
            ["node", "--check", path], capture_output=True, text=True, timeout=10
        )
        assert proc.returncode == 0, proc.stderr[:500]
    finally:
        Path(path).unlink(missing_ok=True)


def test_probe_against_dom_stub():
    if not shutil.which("node"):
        pytest.skip("node not available")
    harness = Path(__file__).parent / "js_harness_check.js"
    assert harness.exists()
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(JS_CHECK_NEW_OUTPUT_V4)
        probe_path = f.name
    try:
        proc = subprocess.run(
            ["node", str(harness), probe_path],
            capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0, proc.stdout[:2000] + proc.stderr[:500]
        payload = json.loads(proc.stdout)
        assert payload.get("ok") is True
    finally:
        Path(probe_path).unlink(missing_ok=True)
