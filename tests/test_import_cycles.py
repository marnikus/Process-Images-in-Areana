"""Every `app.services` / `app.browser` module must import on its own (audit #4 N7).

Making the new-tab handover end a reconcile pass reached for `live.reconcile`
directly, and that closed a cycle:

    cooldown_service -> new_tab -> live.reconcile -> reconcile_rows -> run_state
                                                                   -> cooldown_service

`import app.services.cooldown_service` then raised ImportError outright and took
22 test modules with it. Every FOCUSED suite still passed, because pytest
happened to import the package in an order that never hit the cycle — only the
full run did.

A cycle is not a style question: it is a module that cannot be imported without
a particular importer, which is exactly what makes code untestable in
isolation. So it is pinned here, for every module in the two layers the I-79
line lives in. This is why `live/pass_hold.py` is a stdlib-only leaf.
"""
from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys

import pytest

LAYERS = ("app.services", "app.browser")


def _modules(layer: str) -> list[str]:
    pkg = importlib.import_module(layer)
    return sorted(m.name for m in pkgutil.walk_packages(pkg.__path__, layer + ".")
                  if not m.ispkg)


@pytest.mark.parametrize("name", [n for layer in LAYERS for n in _modules(layer)])
def test_a_module_imports_with_no_importer_of_its_own(name: str):
    """Import it FIRST, in a fresh interpreter — nothing may already be in sys.modules."""
    result = subprocess.run([sys.executable, "-c", f"import {name}"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"{name} cannot be imported on its own:\n{result.stderr[-800:]}"
