"""Workspace architecture — import direction locks (design §C.1).

`app/persistence/workspace/**` and `app/services/workspace/**` must never
import `app.ui*`; the coordinator/registry must not grow a Qt dependency
feature by feature. AST-based, no runtime import needed.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNED = [ROOT / "app" / "persistence" / "workspace",
           ROOT / "app" / "services" / "workspace"]

pytestmark = pytest.mark.unit


def _py_files():
    for base in SCANNED:
        yield from base.rglob("*.py")


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


@pytest.mark.parametrize("banned", ["app.ui", "PySide6", "PyQt6"])
def test_workspace_packages_stay_qt_and_ui_free(banned):
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _imports(tree):
            root_pkg = module.split(".")[0]
            assert not module.startswith(banned), f"{path.name} imports {module}"


def test_providers_do_not_import_the_coordinator():
    """A provider pulling the coordinator in would invert the layering (god service)."""
    for path in (ROOT / "app" / "services" / "workspace" / "providers").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _imports(tree):
            assert "coordinator" not in module and not module.endswith(".save") \
                and not module.endswith(".restore"), f"{path.name} imports {module}"


def test_registry_table_matches_restore_order():
    from app.services.workspace.registry import RESTORE_ORDER, all_providers
    assert [p.domain_id for p in all_providers()] == list(RESTORE_ORDER)
    assert len(set(RESTORE_ORDER)) == len(RESTORE_ORDER)


def test_every_provider_keeps_the_contract():
    from app.services.workspace.registry import all_providers
    for provider in all_providers():
        assert provider.domain_id and provider.display_name
        assert provider.sensitivity in ("public", "personal", "secret")
        assert isinstance(provider.required, bool)
        if provider.native_rel_path:
            assert provider.native_rel_path.startswith("state/")
        capture = provider.capture
        assert callable(capture) and callable(provider.validate)
        assert callable(provider.apply) and callable(provider.reconcile)


def test_restore_order_helper_puts_registry_first_then_unknowns():
    """D2/D3: ONE id-ordering helper for preview AND strict expansion."""
    from app.services.workspace.registry import RESTORE_ORDER, restore_order
    assert RESTORE_ORDER, "sanity"
    sample = [RESTORE_ORDER[-1], "not_a_domain", RESTORE_ORDER[0]]
    assert restore_order(set(sample)) == [RESTORE_ORDER[0], RESTORE_ORDER[-1], "not_a_domain"]
    assert restore_order(set()) == []
